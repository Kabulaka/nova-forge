---
name: nova-review
description: 在用户明确要求 Review 时，按稳定工作项编号选择一个或多个已提交变更，复用有效测试证据，组织独立只读代码审查、修复复审，并在 PASS 后确定性关闭蓝图待办和写入分片审计。用于“开始 Review”、审查指定 PEND/FIX/MAINT 编号、审查全部未审项、查询 Review 状态或补齐历史 Review；不用于默认编码、普通调试、自动提交、PR 泛化建议或用户未授权的 Review。
---

# Nova 人工 Review

只在用户明确提出 Review、审查、复审、补审或查询审计状态时运行。技能被加载不等于用户已授权启动 Review；普通实现、测试和本地 commit 不得自动进入本流程。

## 1. 固定选择范围

先读取 [工作项与提交契约](references/commit-contract.md)，再用 `scripts/nova_review.py select` 得到候选：

- 裸“开始 Review”：`current`，只取当前会话明确记录为 ready、且 `Review-Policy: required` 的编号；
- 用户列出编号：`explicit`，只取所列 `PEND-*`、`FIX-*` 或 `MAINT-*`，允许多个；
- 用户明确“全部未审查项”：`all`，才扫描全部带 Nova trailers 且尚无 Review 记录的提交。

固定每项的编号、commit 列表、设计引用、有效测试证据、未验证事项和工作副本差异。SVN/Git 历史中不属于这些编号的旧改动不得纳入。选择为空时报告原因，不把空范围当 PASS。

候选编号只能来自用户输入、当前会话 ready 记录或既有 commit trailers。Review 不得调用 `new-id`、补造编号或替换编号；审查发现的当轮修复提交也必须沿用被审工作项。选择阶段若可信审计已归档该编号但又出现未覆盖的新 commit，必须在启动 Reviewer 前失败并要求重新分类建项；不得把归档关系当作重新打开原工作项。

## 2. Review 可被人工中断

用户要求先调试、继续修改、暂停或取消 Review 时，停止尚未开始的新审查；不新增审计记录、不关闭待办，保留已有 commit、仍有效的测试证据及中断前已取得的明确 Review 结论。后续再次 Review 时按内容标识复用未失效结论，并从提交 trailers 选择同一工作项尚无有效结论的提交。

## 3. 执行独立审查

完整读取 [Review SOP](references/review-sop.md)。主代理先完成范围/验收映射和自检，再把完整指定 diff、内容标识、意图、有效测试证据与未验证事项交给独立只读子代理。Review 子代理不得修改代码、递归委派或把范围外历史问题算入结论。

REJECT 时主代理统一修复全部 Blocker 与 Observation-Fix；只重跑被修复失效的测试，并复用原审查者增量复审。最多三轮。没有 PASS、PASS WITH NOTES 或 REJECT 的明确结论时不得形成审计结果。

## 4. PASS 后关闭

PASS 或按 SOP 合法的 PASS WITH NOTES 后，读取 [审计与关闭契约](references/audit-contract.md)。用 `scripts/nova_review.py record-pass` 对同批一个或多个工作项执行确定性关闭：

- `PEND-*`：从蓝图删除，工作包改为已完成，按需把设计置为已实现；
- 活动蓝图行含 `需求引用` 时：只解析 `.nova/PRODUCT_REQUIREMENTS.md` 的需求索引行并更新已实现版本、状态和 PEND 实现依据，不读取需求块正文；Review 版本落后于当前需求版本时保持“已更新”；
- `FIX-*` / `MAINT-*`：不要求蓝图条目，只记录提交与 Review 批次；
- 所有项：年度功能 JSONL 追加完成记录，月度目录新增一份严格 JSON-in-YAML Review 记录，并写入工作项哈希索引。

关闭前先 `check-manifest`。失败时不得手工补一半台账；修正输入后重试同一批次。相同批次和内容重复执行必须复用既有记录。

关闭提交完成且 `query` 可信校验通过后，完整读取整个 [实施与交付 SOP](../nova-development/references/implementation-sop.md)，随后严格使用其第 7 节固定结构向用户报告最终结果。所有章节不得省略；必须按实际结果更新提交、Review 状态与轮次、内容标识与范围、逐轮问题处置、蓝图/设计/审计、基线清理和遗留事项，无内容写“无”。不得用简化的 Review 摘要替代固定完成报告。

## 5. 工具入口

```bash
python3 scripts/nova_review.py validate-message --repo /path/to/repo --message-file /path/to/message --diff-file /path/to/diff
python3 scripts/nova_review.py validate-audit-message --repo /path/to/repo --message-file /path/to/message --diff-file /path/to/diff
python3 scripts/nova_review.py select --repo /path/to/repo --mode current --session-item PEND-001
python3 scripts/nova_review.py check-manifest --repo /path/to/repo --manifest /path/to/review.json
python3 scripts/nova_review.py record-pass --repo /path/to/repo --manifest /path/to/review.json
python3 scripts/nova_review.py query --repo /path/to/repo --work-item PEND-001
python3 scripts/validate_discovery.py --workspace /path/to/skills --codex-home /path/to/.codex
python3 scripts/probe_default_flow.py
```

工具只使用 Python 标准库。`validate-message`、`validate-audit-message`、`select`、`check-manifest`、`query` 和 `query-requirement` 只读；Work-Item 的 `validate-message --repo` 额外校验当前编号未归档及 `Related-Work-Item` 的可信归档来源，requirement 检查点则强制同时提供 `--repo` 与完整 staged diff，并校验精确范围、路径、内容指纹和唯一性。`select` 只发现 PEND/FIX/MAINT，排除 requirement 与 audit commit。`record-pass` 是唯一写审计/关闭入口。`probe_default_flow.py` 只在隔离临时 Git 仓库调用本机 Codex，验证普通开发自动 commit 且不 Review、显式 Review 才进入选择。关闭生成的文件使用提交契约中的 `Nova-Audit-Schema` trailers 单独提交，不形成新工作项或递归 Review。

## 资源路由

| 条件 | 完整读取 |
|------|----------|
| 选择范围、生成或校验 commit trailers | `references/commit-contract.md` |
| 启动独立 Review 或复审 | `references/review-sop.md` |
| 查询、记录 PASS 或关闭正式待办 | `references/audit-contract.md` |
| PASS/PASS WITH NOTES 关闭并完成可信查询后的用户报告 | `../nova-development/references/implementation-sop.md` 完整文件；最终报告使用第 7 节 |
