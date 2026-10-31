---
name: project-handoff
description: Create or replace a concise PROJECT_STATUS.md snapshot so a future AI can quickly understand the project's current state with minimal context. Use only when the user explicitly invokes $project-handoff or directly asks to refresh the project handoff snapshot; do not trigger automatically when starting, modifying, or finishing other work.
---

# Project Handoff

将仓库当前状态压缩为一份可替换的 `PROJECT_STATUS.md`，供下一次 AI 快速接手。目标是减少上下文和 Token 消耗，不是保存审计历史或证明代码正确。

## 执行流程

1. 读取仓库根目录现有的 `PROJECT_STATUS.md`（如有），只用它识别需要更新的上下文，不继承与当前状态冲突的内容。
2. 只执行必要的只读检查：
   - `git status --short --branch`
   - `git log -10 --oneline --decorate`
   - `git diff --stat` 和 `git diff --cached --stat`（仅在存在未提交修改时）
3. 根据当前对话、Git 状态、最近提交和必要的核心文件，判断项目当前已完成内容、正在进行内容、关键约定、已知问题和下一步。
4. 直接覆盖仓库根目录 `PROJECT_STATUS.md`，只保留最新状态，不追加历史快照。
5. 报告快照已更新及其路径；如存在未提交修改，简短说明快照包含工作区状态。

只在无法从上述信息判断关键状态时读取额外文件。优先读取入口文件、配置文件或与最近提交直接相关的文件，避免遍历整个仓库。

## 快照格式

保持简洁，省略无内容的可选小节。通常控制在 120 行以内。

```markdown
# PROJECT STATUS

> 更新时间：<ISO 8601 时间>
> Git：<分支> @ <短 SHA；若有未提交修改则注明 dirty>

## 项目概况

<用 2～4 句话说明项目用途、当前阶段和主要技术链路。>

## 当前状态

- 已完成：<已经落地且仍有效的核心能力>
- 进行中：<当前尚未完成的工作；没有则写“无”>
- 当前阻塞：<真正影响继续开发的问题；没有则写“无”>

## 关键实现与约定

- <后续 AI 修改代码前必须知道的架构、数据口径或工程约定>

## 关键位置

- `<path>`：<用途>

## 最近变更

- `<commit>`：<与当前状态有关的简短说明>
- <未提交修改摘要；没有则省略>

## 下一步

1. <最优先且可执行的事项>
2. <后续事项>

## 已知问题

- <仍需注意的问题；没有则写“无”>
```

## 明确禁止

- 不运行测试、构建、Lint、类型检查、服务或数据库验证。
- 不为了生成快照而读取测试输出或重新核验历史结论。
- 不创建或维护历史索引、归档目录、标签或 handoff 专用提交。
- 不执行 `git add`、`git commit`、`git push`、分支切换或历史改写。
- 不修改 `PROJECT_STATUS.md` 之外的项目文件。
- 不记录密码、令牌、连接凭据或其他敏感值。
- 不复制完整 diff、提交列表、目录树或长篇实现细节。

## 状态表达

- 已提交内容以当前 `HEAD` 和最近提交为准。
- 未提交内容可写入“进行中”或“最近变更”，并明确标为未提交。
- 无法确认的事项写“待确认”，不要运行测试来证明。
- 后续功能被修改并重新提交后，下一次人工调用本技能时直接用最新 Git 状态覆盖旧快照。
