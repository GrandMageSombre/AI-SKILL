---
name: conventional-commit
description: 编写符合 Conventional Commits 规范的 git 提交信息。触发词：提交代码、写 commit message、整理提交历史、生成 CHANGELOG、版本号怎么定。用户没明说时，按本规范写中文提交信息。
---

# Conventional Commits 提交规范

规范的提交信息是项目的第一手文档：三个月后回看 `git log`，一眼就知道"这次为什么改、改了什么"。

## 一、格式

```
<类型>(<范围>): <描述>

<正文：为什么改 / 改了什么 / 怎么验证>

<脚注：BREAKING CHANGE / Closes / Co-authored-by>
```

## 二、类型（必填第一个词）

| 类型 | 用于 | 版本号影响 |
|------|------|------------|
| `feat` | 新功能 | **minor +1**（1.2.0 → 1.3.0） |
| `fix` | 修 bug | **patch +1**（1.3.0 → 1.3.1） |
| `docs` | 只改文档/注释 | 不变 |
| `style` | 纯格式（空格、分号、引号），不改语义 | 不变 |
| `refactor` | 重构：既不加功能也不修 bug | 不变 |
| `perf` | 性能优化 | 不变 |
| `test` | 只加/改测试 | 不变 |
| `build` | 构建系统、依赖、打包配置 | 不变 |
| `ci` | 自动化流水线 | 不变 |
| `chore` | 杂项（.gitignore、清缓存、格式化） | 不变 |
| `revert` | 回滚某次提交 | 不变 |

**破坏性变更**（删接口、改协议、不兼容配置）：类型后加 `!` + 脚注 `BREAKING CHANGE:` → **major +1**（1.x → 2.0.0）。

```bash
feat!: 帧协议载荷改为 float32, 旧的 int16 固件不再兼容

BREAKING CHANGE: 上位机与固件需同步升级, 混用会导致通道数值错乱
```

## 三、范围（可选，但强烈建议填）

用**目录名或模块名**，让人一眼定位改动位置：

```bash
fix(protocol): 擦除帧超过 bootloader 接收缓冲导致 NACK
docs(tests): 补充 HEX 重叠段用例
feat(ui): 多字符串发送内嵌串口助手页
build(packaging): PyInstaller 打包排除 .workbuddy
```

## 四、描述（第一行，决定成败）

- **中文**（团队语言），**动词开头**，说清"做了什么"
- **≤ 50 字**，结尾**不加句号**
- ❌ 反面：`更新` / `修改了一些东西` / `fix bug` / `优化代码`
- ✅ 正面：`修复 HEX 重叠段保留旧值的问题` / `新增 DTR/RTS 控制线自由配置`

## 五、正文（复杂改动必写）

三段式，Markdown 列表：

```bash
git commit -F- <<'EOF'
fix(protocol): LEN 超限判错并重同步, 防止吞帧

伪造的大 LEN 会让解析缓冲长时间等一个永远到不了的帧,
期间到达的正常帧被连带丢弃(见审查报告6 #1)。

- 新增 MAX_PAYLOAD=64 上限, 超限按错误帧处理并计数
- 补测试: 伪造 LEN=255 后紧跟正常帧, 验证正常帧仍被解析

测试: python tests/test_protocol.py (12 项全过)
EOF
```

正文回答三个问题：**为什么改**（动机/来源）、**改了什么**（要点列表）、**怎么验证的**（跑了什么、结果如何）。

## 六、脚注

```bash
Closes: #12              # 关闭 issue
Fixes: #7                # 同上
Co-authored-by: 姓名 <邮箱>   # 协作提交
BREAKING CHANGE: 说明     # 配合类型后的 ! 使用
```

## 七、怎么写多行提交信息

```bash
# 方式一：heredoc（Linux/macOS/Git Bash 通用，推荐）
git commit -F- <<'EOF'
feat(ui): 多字符串发送

- 内嵌为串口助手页第四节
- 循环发送运行中禁用结构编辑
EOF

# 方式二：多个 -m（每段一个 -m，段间自动空行）
git commit -m "fix(ui): 关串口未停止循环发送" -m "原先靠 tick 检测, 间隔最长 10min 有延迟窗口。close_port 主动调用 stop_loop。"

# 方式三：写文件（Windows 最稳，避开 shell 编码问题）
# 先用编辑器写 commit.txt，再：
git commit -F commit.txt
```

## 八、提交前检查清单

- [ ] 类型选对了？（新功能 `feat` / 修 bug `fix` / 只改文档 `docs`）
- [ ] 范围填了吗？（`ui` / `core` / 具体模块名）
- [ ] 第一行能让人一眼看懂这次干了什么？
- [ ] 复杂改动写了正文（动机/改动/验证）？
- [ ] 测试跑过了？版本号按类型联动了吗？
- [ ] 一次提交只干一件事（别把重构和功能混在一起）

## 九、常见反模式

| 反模式 | 问题 | 正确做法 |
|--------|------|----------|
| `update` / `修改` | 没有信息 | `feat(ui): 增加曲线导出 CSV` |
| 一次提交改了 5 个不相关功能 | 无法单独回滚，log 失真 | 拆成 5 次提交 |
| `fix bug in serial tab and curve` | 范围和描述都超长 | `fix(ui): 修复曲线页暂停后统计继续累加` |
| 只写标题不写正文（复杂改动） | 丢失动机，后人重复踩坑 | 补正文三段式 |
| 提交里混入调试代码/大二进制 | 污染历史，仓库膨胀 | 先清理，或加 `.gitignore` |

## 十、与审查流程的衔接

完整开发流程：**实现 → 测试 → 多智能体四视角审查 → 修复 → 更新审查报告与版本说明 → 按本规范提交推送**。
审查流程详见 `code-review` skill。
