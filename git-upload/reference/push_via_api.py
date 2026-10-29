#!/usr/bin/env python3
"""github.com:443 被代理拦截时，用 GitHub REST API 把本地 HEAD 推到远端分支。

原理：commit 的 SHA 由 tree + parent + author/committer（含时间戳与偏移）+ message
唯一决定。这些全部照抄本地，GitHub 生成的 SHA 与本地完全相同，不会造成远端分叉。

用法（在仓库根目录执行）：
    python push_via_api.py --dry-run    # 建 blob / tree 并比对，不动分支
    python push_via_api.py              # 真推

依赖：git（已配置 origin）、GCM 里存过 github.com 的凭据。
"""

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------- git helpers

def git(*args, binary=False):
    r = subprocess.run(['git', *args], capture_output=True, timeout=180)
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败: {r.stderr.decode('utf-8', 'replace')[:300]}")
    return r.stdout if binary else r.stdout.decode('utf-8', 'replace')


def parse_remote(url):
    """https://github.com/OWNER/REPO.git 或 git@github.com:OWNER/REPO.git -> OWNER/REPO"""
    u = url.strip()
    if u.startswith('git@'):
        u = u.split(':', 1)[1]
    else:
        u = u.split('github.com/', 1)[1]
    return u[:-4] if u.endswith('.git') else u


def token_from_gcm():
    env = {**os.environ, 'GCM_INTERACTIVE': 'never',
           'GIT_TERMINAL_PROMPT': '0', 'GCM_PROVIDER': 'github'}
    r = subprocess.run(['git', 'credential', 'fill'],
                       input='protocol=https\nhost=github.com\n\n',
                       capture_output=True, text=True, timeout=40, env=env)
    for line in r.stdout.splitlines():
        if line.startswith('password='):
            return line.split('=', 1)[1].strip()
    raise SystemExit('取不到 GitHub token（GCM 里没有 github.com 凭据）')


def to_iso(ts, tz):
    sign = 1 if tz[0] == '+' else -1
    off = sign * (int(tz[1:3]) * 60 + int(tz[3:5]))
    dt = datetime.fromtimestamp(int(ts), tz=timezone(timedelta(minutes=off)))
    return dt.strftime('%Y-%m-%dT%H:%M:%S') + tz[:3] + ':' + tz[3:]


# ---------------------------------------------------------------- API

def make_api(token):
    def api(path, method='GET', body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            'https://api.github.com' + path, data=data, method=method,
            headers={'Authorization': 'Bearer ' + token,
                     'Accept': 'application/vnd.github+json',
                     'User-Agent': 'wb',
                     'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode() or '{}'
                return resp.status, json.loads(raw)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:300]
    return api


# ---------------------------------------------------------------- main

def main():
    dry = '--dry-run' in sys.argv
    repo = parse_remote(git('remote', 'get-url', 'origin'))
    branch = git('rev-parse', '--abbrev-ref', 'HEAD').strip()
    api = make_api(token_from_gcm())

    head = git('rev-parse', 'HEAD').strip()
    head_tree = git('rev-parse', 'HEAD^{tree}').strip()

    headers, message = git('cat-file', '-p', 'HEAD').split('\n\n', 1)
    parents = [l.split()[1] for l in headers.splitlines() if l.startswith('parent ')]
    author = [l for l in headers.splitlines() if l.startswith('author ')][0][len('author '):]
    name_email, ts, tz = author.rsplit(' ', 2)
    name, email = name_email[:-1].split(' <')
    iso = to_iso(ts, tz)

    print(f'repo    : {repo}')
    print(f'branch  : {branch}')
    print(f'head    : {head}')
    print(f'tree    : {head_tree}')
    print(f'parent  : {parents[0] if parents else "(root)"}')
    print(f'author  : {name} <{email}> {iso}')

    st, ref = api(f'/repos/{repo}/git/ref/heads/{branch}')
    if st == 200:
        remote_sha = ref['object']['sha']
        st2, rcommit = api(f'/repos/{repo}/git/commits/{remote_sha}')
        remote_tree = rcommit['tree']['sha']
    elif st == 404:
        remote_sha, remote_tree = None, None
    else:
        raise SystemExit(f'读远端分支失败: {st} {ref}')

    print(f'remote  : {remote_sha or "(分支不存在)"}')

    if remote_sha == head:
        print('远端已经就是本地 HEAD，无需推送。')
        return
    if remote_sha and remote_sha != (parents[0] if parents else None):
        raise SystemExit(
            '远端分支不是本地 HEAD 的父提交，不能直接复刻（会产生分叉）。\n'
            '先按 SKILL §五 接续历史：fetch → checkout -B <branch> <remote-sha> → 补提交。')

    # ---- 比对文件，收集要传的 blob 与要删的项
    local = {}
    for rec in git('ls-tree', '-r', '-z', 'HEAD').split('\0'):
        if not rec:
            continue
        meta, path = rec.split('\t', 1)
        mode, _type, sha = meta.split()
        local[path] = (mode, sha)

    remote_files = {}
    if remote_tree:
        st, data = api(f'/repos/{repo}/git/trees/{remote_tree}?recursive=1')
        if st != 200:
            raise SystemExit(f'读远端 tree 失败: {st} {data}')
        remote_files = {t['path']: t for t in data['tree'] if t['type'] == 'blob'}

    entries = []
    for path, (mode, sha) in local.items():
        if remote_files.get(path, {}).get('sha') == sha:
            continue
        content = git('cat-file', 'blob', sha, binary=True)
        st, res = api(f'/repos/{repo}/git/blobs', 'POST',
                      {'content': base64.b64encode(content).decode(), 'encoding': 'base64'})
        if st != 201 or res.get('sha') != sha:
            raise SystemExit(f'blob 上传异常 {path}: {st} {res}')
        entries.append({'path': path, 'mode': mode, 'type': 'blob', 'sha': sha})
        print(f'  blob  {path}')

    for path in remote_files:
        if path not in local:
            entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': None})
            print(f'  del   {path}')

    # ---- 建树并比对
    body = {'tree': entries}
    if remote_tree:
        body['base_tree'] = remote_tree
    st, tree = api(f'/repos/{repo}/git/trees', 'POST', body)
    if st != 201:
        raise SystemExit(f'建 tree 失败: {st} {tree}')
    print(f'new tree: {tree["sha"]}  与本地一致: {tree["sha"] == head_tree}')
    if tree['sha'] != head_tree:
        raise SystemExit('tree 与本地不一致，停下（检查是否有 CRLF 转换或漏传文件）')

    if dry:
        print('\n[dry-run] 到此为止，分支未改动。')
        return

    # ---- 建提交并比对 SHA
    st, commit = api(f'/repos/{repo}/git/commits', 'POST',
                     {'message': message, 'tree': head_tree,
                      'parents': [remote_sha] if remote_sha else [],
                      'author': {'name': name, 'email': email, 'date': iso},
                      'committer': {'name': name, 'email': email, 'date': iso}})
    if st != 201:
        raise SystemExit(f'建 commit 失败: {st} {commit}')
    print(f'new commit: {commit["sha"]}  与本地一致: {commit["sha"] == head}')
    if commit['sha'] != head:
        raise SystemExit('commit SHA 与本地不一致（message 末尾换行或日期偏移？），分支未改动')

    # ---- 移动分支
    st, res = api(f'/repos/{repo}/git/refs/heads/{branch}', 'PATCH',
                  {'sha': commit['sha'], 'force': False})
    if st != 200:
        raise SystemExit(f'更新分支失败: {st} {res}')
    print(f'[OK] {branch} -> {res["object"]["sha"]}')


if __name__ == '__main__':
    main()
