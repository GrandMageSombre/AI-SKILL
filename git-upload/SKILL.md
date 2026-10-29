---
name: git-upload
description: 把本地文件夹变成 GitHub 仓库并推送上去，含远端存在性检查、线性历史接续、认证与 502 排查、无 gh CLI 时走 API、github.com 被墙时用 REST API 复刻提交。触发词：上传到 GitHub、加入 git 管理、建仓库、推代码、push 失败、git init、把项目传到 github、发布到仓库、CONNECT 502、non-fast-forward。
---

# 本地目录 → GitHub

一次做对的关键只有三件事：**先查远端有没有这个仓库**、**别覆盖远端已有的提交**、**push 失败要看返回码再决定后续动作**。

## 一、何时触发

- "把这个文件夹加入 git 管理 / 上传到 github / 建个仓库推上去"
- `push` 报 502、认证失败、non-fast-forward
- 机器上没有 `gh` CLI，或 github.com 连不上但 api.github.com 正常

## 二、流程总览

| 步 | 做什么 | 关键判断 |
|---|---|---|
| 1 | 查远端是否已有同名仓库 | **先查再建**，重名会推到别人/旧的仓库去 |
| 2 | 本地 `init` + `.gitignore` | `git init -b main`，先把运行时目录挡掉 |
| 3 | 提交 | Conventional Commits；中文信息写文件再 `-F` |
| 4 | 接远端 | 远端为空 → 直接 push；**已有提交 → 走 §五** |
| 5 | push | 502 / 认证 / 非快进 → §七 |
| 6 | 校验 | API 查 tree + `git status -sb` |

## 三、先查远端，别急着建仓库

用户说"仓库已经有了"时，**先列出来核实**（列全部仓库按名字找），不要新建重名资源。

```python
GET /repos/{owner}/{repo}        # 200 = 已存在；404 = 可以建
GET /user/repos?per_page=100     # 一次列全，按 name 找
```

```python
def api(path, method='GET', body=None, token=TOKEN):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        'https://api.github.com' + path, data=data, method=method,
        headers={'Authorization': 'Bearer ' + token,
                 'Accept': 'application/vnd.github+json',
                 'User-Agent': 'wb',
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode() or '{}')
```

建空仓库（先确认 404）：

```python
POST /user/repos {"name": "xxx", "private": False, "description": "一句话说明"}
```

## 四、本地初始化与提交

```bash
git init -b main
git add -A
git -c i18n.commitEncoding=utf-8 commit -F .git/MSG.tmp
rm .git/MSG.tmp
```

- 提交信息规范见 `conventional-commit` skill（`类型(范围): 描述`，feat→minor、fix→patch）
- 中文提交信息**写进文件再 `-F`**，别走 shell 变量，Windows 下会撞编码
- `.gitignore` 至少挡掉：工具运行时目录（如 `.workbuddy/`）、`__pycache__/`、`node_modules/`、编辑器目录

## 五、远端已有提交：接上去，不要覆盖

典型分叉场景：本地是一个 root commit，远端已经有历史（往往是同一批文件 + 更完整的 README）。

```bash
git remote add origin <url>
git fetch origin main:refs/remotes/origin/main --force
git branch backup-initial main           # 备份本地 root commit，出事能回
```

**切换前先把本地新增的东西复制到仓库外**（例如 `%TEMP%/bak`）——`checkout` 到远端基线时，已在版本库里的文件会被删掉：

```bash
git checkout -B main <remote-sha>        # 工作区切到远端基线
# 把 bak 里的目录/文件拷回来，再提交
git add -A && git commit -F .git/MSG.tmp
git branch -D backup-initial             # 确认无误后清理
```

要点：

- **远端的 README 等既有文件不要用你本地新写的覆盖**，看完内容在其上增补
- 只构造线性历史（`fetch` + `checkout -B` + 补提交），不制造无谓的 merge commit
- 全程只用 `init / add / commit / fetch / checkout / push`，**不用 rebase / cherry-pick / reset --hard**（见 §十一）

## 六、push

```bash
git push -u origin main
```

## 七、push 失败怎么看

| 报错 | 真实原因 | 处置 |
|---|---|---|
| `CONNECT tunnel failed, response 502` | 代理拦了 `github.com:443`（`api.github.com` 通常仍通） | ① 重试 2~3 次，常常是间歇的 ② 仍不行走 §九 |
| `schannel: failed to receive handshake` | 同上，TLS 握手被中断 | 同上 |
| `Authentication failed` / 反复要密码 | 没有可用凭据 | 走 §八 取 token |
| `! [rejected] ... non-fast-forward` | 远端有你本地没有的提交 | 先 `fetch` 看差异，**不要 `--force`** |
| `src refspec main does not match any` | 还没 commit，或分支名不对 | `git log` 确认有提交、`git branch` 确认名字 |

判别方法：`api.github.com` 能通而 `github.com` 不通，就是代理策略，不是你的凭据问题。

## 八、没有 gh CLI：从凭据管理器取 token

```python
env = {**os.environ, 'GCM_INTERACTIVE': 'never',
       'GIT_TERMINAL_PROMPT': '0', 'GCM_PROVIDER': 'github'}
r = subprocess.run(['git', 'credential', 'fill'],
                   input='protocol=https\nhost=github.com\n\n',
                   capture_output=True, text=True, timeout=40, env=env)
token = [l.split('=', 1)[1].strip()
         for l in r.stdout.splitlines() if l.startswith('password=')][0]
```

- `gho_` 前缀是 GitHub OAuth token；用 `GET /user` 看响应头 `X-OAuth-Scopes` 是否含 `repo`
- 把 `GCM_INTERACTIVE=never` 设上，否则可能弹窗卡死
- **token 不进日志、不进提交、不写进 skill 文件**

## 九、github.com 被拦时：用 REST API 复刻提交

原理：commit 对象的 SHA 由 **tree + parent + author/committer（含时间戳与偏移）+ message** 唯一决定。只要这些照抄本地，GitHub 生成的 SHA 与本地**完全相同**，不会造成远端分叉。

```
POST  /git/blobs              # 逐个改动文件，base64
POST  /git/trees              # {base_tree: 远端 tree, tree: [{path,mode,type,sha}]}，删除项 sha 传 null
POST  /git/commits            # {message, tree, parents, author, committer}
PATCH /git/refs/heads/main    # {sha, force: false}
```

四个必守的细节：

1. **内容用 `git cat-file blob <sha>` 取字节**，别读工作区文件（工作区可能被 CRLF 转换污染，SHA 就会变）
2. **message 保留末尾换行**；author/committer 日期用**带 `+08:00` 偏移**的 ISO 格式，别转成 UTC
3. 建完 tree 先比对 `tree.sha == git rev-parse HEAD^{tree}`，不等就**停下**，别继续提交
4. 建完 commit 再比对 `sha == git rev-parse HEAD`；一致才 PATCH ref

现成脚本：`reference/push_via_api.py`

```bash
python push_via_api.py --dry-run   # 只建 blob/tree 并比对，不动分支
python push_via_api.py             # 真推
```

## 十、收尾校验

```bash
git status -sb            # 期望：## main...origin/main，既无 [gone] 也无 ahead/behind
git log --oneline -3
```

```python
GET /repos/{owner}/{repo}/git/trees/main?recursive=1   # 核对远程文件清单与大小
```

> ⚠️ **`git push` 返回码为 0 之后才更新 `refs/remotes/origin/main`。** 先写后验会让 `git status` 假装已同步，实际远端没变——排查时会多花一倍时间。

## 十一、本机红线（Windows 沙箱）

- **Bash 工具缺 coreutils**（`ls/head/dirname` 全 not found）→ 一律用 `python -c` + `subprocess` 跑 git
- **`git` 写 `refs/remotes/origin/*` 会静默失败**（rc=0 但文件没生成，`status` 显示 `[gone]`）→ 用 Python `os.makedirs` + 直接写 ref 文件（完整 sha + `\n`）
- **禁用 `rebase` / `cherry-pick` / `reset --hard`**：大量增删 `.git` 内文件会触发沙箱 safe-delete，把整个 `.git` 删掉
- 无 `gh` CLI；GitHub 认证走 §八

## 十二、速查

| 我要… | 怎么做 |
|---|---|
| 确认远端有没有这个仓库 | `GET /repos/{owner}/{repo}` |
| 建空仓库 | `POST /user/repos` |
| 接远端已有历史 | `fetch` → 备份新文件 → `checkout -B main <sha>` → 拷回 → 补提交 |
| push 报 502 | 重试 2~3 次；仍失败走 §九 API 复刻 |
| 确认真的推上去了 | `git status -sb` + API 查 `trees/main` |
| 中文提交信息 | 写文件 + `git -c i18n.commitEncoding=utf-8 commit -F` |
