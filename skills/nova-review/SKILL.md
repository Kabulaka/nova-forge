---
name: nova-review
description: 仅在用户明确要求时，对指定 Git/SVN 提交、范围或当前任务差异执行独立只读代码审查、统一修复、复测与同一 reviewer 复审。保留严格范围、显式思考度、问题分级和最多三轮规则；不维护审计、编号、蓝图 Review 状态或流程数据。
---

# Nova 人工 Review

只在用户明确提出 Review、审查、复审或补审时运行。技能被加载不等于用户已授权启动 Review；普通实现、测试和本地 commit 不得自动进入本流程。

## 1. 固定审查范围

优先使用用户指定的 commit、SHA range、分支差异、SVN revision 或工作树范围。范围不明确且不同选择会改变审查对象时，完整读取 [共享澄清 SOP](../nova-development/references/conversation-sop.md)，只问一个范围问题。

固定任务开始基线、目标 commits、路径与行块、变更意图、验收标准、有效测试证据、未验证事项和工作副本中的既有修改。只审当前任务差异：

- 工作副本中的历史修改不因出现在 diff 中自动纳入；
- SVN/Git 历史中的相邻变更不得自动纳入；
- 范围外问题不分级、不影响结论；确实阻止验收时只报告基线风险，由用户决定是否扩围；
- 选择为空或无法可靠分离当前任务差异时报告原因，不把空范围当 PASS；
- 固定范围后不得为了“顺手检查”扫描全部历史或扩大到其他任务。

## 2. 人工中断

用户要求先调试、继续修改、暂停或取消 Review 时，停止尚未开始的新轮次，并可按用户指令中断正在运行的 Reviewer。中断不是 Review 结论；保留已有 commits、工作副本、有效测试证据和中断前取得的明确结论。后续继续时按内容标识复用未失效证据和结论。

## 3. 独立审查

启动前必须完整读取 [Review SOP](references/review-sop.md)，不得用本文件摘要替代其中长期积累的规则。只有范围存在真实歧义时才额外加载共享澄清 SOP。

主代理先完成任务差异自检和验收映射，再向独立只读 Reviewer 提供完整 diff、基线内容标识、变更意图、验收、有效测试证据、未验证事项，以及显式 `reasoning_effort`。Reviewer 不得修改工作副本、递归委派、运行无关长任务或把范围外历史问题纳入结论。

Reviewer 必须完成契约、边界与异常、测试、架构、性能、副作用和代码风格七个维度后，一次性返回：

- `PASS`：无 Blocker、无 Observation；
- `PASS WITH NOTES`：无 Blocker、无 Observation-Fix，只有符合延期准入条件的 Observation-Defer；
- `REJECT`：存在 Blocker 或 Observation-Fix。

每个问题必须包含维度、严重性、文件与行号、证据和可执行修复方向。不得把风格偏好、范围外既有问题或纯理论低概率风险升级为 Blocker。

## 4. 修复与复审

REJECT 后主代理统一修复全部 Blocker 和 Observation-Fix，不借机重构无关代码；只重跑因修复失效的测试，其他证据必须复用。修正保持未提交，交给同一 Reviewer 复审旧问题和修复直接触及的行。

初审是第 1 轮，随后最多两次复审，总计三轮。第 3 轮仍 REJECT 时停止并报告；不得开始第 4 轮或伪造 PASS。只有 Reviewer 生命周期失败或因写入失去审查资格时才可更换，且轮次不得重置。

## 5. PASS 后提交与报告

- PASS 或合法 PASS WITH NOTES 后结束审查，不生成审计、manifest、closure transaction、工作项编号、Review 状态或 Nova trailers。
- 确有 Review 修正且复审通过时，创建一个普通 Conventional Commit；只有安全且未共享历史时才 amend。
- 没有修正时不创建空提交；不修改蓝图或设计记录 Review。
- 不自动 push、发布、修改远程或提交 SVN。
- 完成报告逐轮列出范围与内容标识、结论、全部问题和修正、验证证据、实际修改路径、提交、刻意未改范围、延期项和遗留风险；不运行报告校验器。
