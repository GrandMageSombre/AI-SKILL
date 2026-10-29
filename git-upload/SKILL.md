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
git fetch origin main --force
git rev-parse origin/main        # 必须能打出 sha，否则见下面“fetch 假成功”
git branch backup-initial main           # 备份本地 root commit，出事能回
```

> ⚠️ **fetch 可能“假成功”**：本机沙箱里 `git fetch` 会打印 `* [new branch] main -> origin/main`（rc=0），
> 但 `refs/remotes/origin/main` 并没有落盘，`git rev-parse origin/main` 直接报 unknown revision。
> 验证失败时改用 sha，不要依赖远程跟踪分支：
>
> ```bash
> git ls-remote origin refs/heads/main   # 输出 "<sha>\trefs/heads/main"
> git fetch origin <sha>                 # 或直接抓对象
> git checkout -B main <sha>
> ```
>
> 全程记住：**只信 sha，不信 `origin/main` 这个名字**。

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

六个必守的细节（前四条来自踩坑复盘）：

1. **只传“变更文件”的 blob，并用 `base_tree` 组装 tree**
   不要用 `git ls-tree -r HEAD` 构造全量 tree——未上传过的新 blob 会让 API 返回
   `422 tree.sha ... is not a valid blob`。正确做法：`diff` 出变动的 path → 逐个建 blob → 以父提交的 tree 作 `base_tree`。
2. **中文路径先关掉 quotePath**
   `git diff --name-status` / `git show HEAD:path` 默认把 `docs/审查报告.md` 输出成
   `docs/\345\256\241...`，直接拿去 `git show` 会 128 失败。统一加 `-c core.quotePath=false`，
   或改用 `git ls-tree -r -z` 按 `\0` 切分。
3. **内容用 `git cat-file blob <sha>` 取字节**，别读工作区文件（工作区可能被 CRLF 转换污染，SHA 就会变）
4. **message 保留末尾换行**；author/committer 日期用**带 `+08:00` 偏移**的 ISO 格式，别转成 UTC
5. 建完 tree 先比对 `tree.sha == git rev-parse HEAD^{tree}`，不等就**停下**，别继续提交
6. 建完 commit 再比对 `sha == git rev-parse HEAD`；一致才 PATCH ref

### 9.1 API 常见错误对照

| 返回 | 含义 | 处理 |
|---|---|---|
| `422 tree.sha ... is not a valid blob` | 用了全量 tree，但新文件的 blob 还没上传 | 改成「只传变更 blob + base_tree」 |
| `422 tree.path ...` 重复 | 同一 path 在 entries 里出现两次 | 去重（重命名 = 删旧 + 加新） |
| `404 Not a valid object name` | 引用了远端不存在的 parent/tree | 先确认 `remote_sha`，并 `git cat-file -e` 验证本地有该对象 |
| `409 Git Repository is empty` | 远端是空仓库 | 直接用 `git push -u origin main` 更简单 |
| `401 Bad credentials` | token 过期/无 `repo` scope | 重取 token（§八） |

### 9.2 PATCH 之后必须回读

PATCH 成功只代表请求被接受。收尾固定三步：

```python
GET /repos/{owner}/{repo}/git/ref/heads/main   # 1. 回读 sha，必须 == 本地 HEAD
```

```python
# 2. 补写本地跟踪引用（本机 git 写 refs/remotes 会静默失败）
import os
sha = subprocess.run(['git','rev-parse','HEAD'], capture_output=True).stdout.decode().strip()
d = os.path.join('.git','refs','remotes','origin')
os.makedirs(d, exist_ok=True)
open(os.path.join(d,'main'),'w').write(sha + '\n')
```

```bash
git status -sb        # 3. 期望 "## main...origin/main"，无 [gone]、无 ahead/behind
```

> ⚠️ **push/复刻失败后不要 amend、不要改写历史。** API 复刻要求 commit SHA 与本地完全一致，
> amend 会让 SHA 变化，之前比对过的 tree/commit 全部作废。

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

## 十一、产物文件与“正在运行的 EXE”

带打包产物的项目（Python/PyInstaller、Electron…）常见两类坑：

**1. 二进制不要入库。** `.gitignore` 至少包含：

```gitignore
dist/
build/
build_pyi/
*.spec.bak
*.exe.old*      # 替换运行中 EXE 时留下的旧备份
```

**2. 运行中的 EXE 不能被覆盖。** Windows 会锁住正在执行的镜像，
`shutil.copy2` 直接抛 `PermissionError: [WinError 32]`。正确姿势是**先改名、再复制**：

```python
import os, shutil, time
dst = r'...\app.exe'
old = dst + f'.old-{int(time.time())}'
if os.path.exists(dst):
    os.rename(dst, old)          # 运行中的旧实例继续用旧文件，不影响
shutil.copy2(new_build, dst)     # 新文件落到原路径
try:
    os.remove(old)               # 旧实例还开着就删不掉，下次再清
except OSError:
    pass
```

> 改名（rename）对正在运行的程序是允许的，删除/覆盖不是。
> 所以“更新正在使用的便携版 EXE”必须走 rename + copy，不要直接写文件。

**3. 一次 push 只复刻一个提交。** `reference/push_via_api.py` 要求
`remote_sha == HEAD 的父提交`。如果本地积压了多个未推送提交，先用 `git push` 重试；
仍被墙时按父→子顺序逐条复刻（每个提交跑一次脚本逻辑），**不要**为了凑成一条而
amend / rebase 改写历史。

## 十二、本机红线（Windows 沙箱）

- **Bash 工具缺 coreutils**（`ls/head/dirname` 全 not found）→ 一律用 `python -c` + `subprocess` 跑 git
- **`git` 写 `refs/remotes/origin/*` 会静默失败**（rc=0 但文件没生成，`status` 显示 `[gone]`）→ 用 Python `os.makedirs` + 直接写 ref 文件（完整 sha + `\n`）；目录不存在时先建目录
- **禁用 `rebase` / `cherry-pick` / `reset --hard`**：大量增删 `.git` 内文件会触发沙箱 safe-delete，把整个 `.git` 删掉（真实事故：一次 rebase 后仓库消失）
- 无 `gh` CLI；GitHub 认证走 §八

## 十三、速查

| 我要… | 怎么做 |
|---|---|
| 确认远端有没有这个仓库 | `GET /repos/{owner}/{repo}` |
| 建空仓库 | `POST /user/repos` |
| 接远端已有历史 | `fetch` → 验证 `rev-parse origin/main`（失败改用 `ls-remote` 的 sha）→ 备份新文件 → `checkout -B main <sha>` → 拷回 → 补提交 |
| push 报 502 | 重试 2~3 次；仍失败走 §九 API 复刻 |
| API 报 422 not a valid blob | 只传变更 blob + `base_tree`，别用全量 tree |
| 路径含中文 | `git -c core.quotePath=false` 或 `ls-tree -z` 按 `\0` 切 |
| 确认真的推上去了 | `git status -sb` + API 回读 `git/ref/heads/main` == 本地 HEAD |
| 中文提交信息 | 写文件 + `git -c i18n.commitEncoding=utf-8 commit -F` |
| 更新正在运行的 EXE | rename 旧文件 → copy 新文件 → 旧文件下次再删 |
