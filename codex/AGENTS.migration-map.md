# 旧 AGENTS.md 约束迁移核对表

本表逐条对应迁移前 `~/.codex/AGENTS.md`。`保留`表示语义进入目标文件；`显式替换`只用于用户已确认的新流程差异，不代表遗漏。运行时权威是“目标”列文件，本表只用于完整性审计。

| ID | 旧约束 | 目标 | 结果 |
|----|--------|------|------|
| A1 | 大匠与规矩 | `codex/AGENTS.global.md#行为准则强制` | 保留原文 |
| A2 | 究本意、击要害 | 同上 | 保留原文 |
| A3 | 求实不浮华 | 同上 | 保留原文 |
| A4 | 方策准确、析疑难 | 同上 | 保留原文 |
| A5 | 先推理后动 | 同上 | 保留原文 |
| A6 | 缺口先问 | 同上 | 保留原文 |
| A7 | 不多言、不饰非 | 同上 | 保留原文 |
| L1 | L0 客观条件与流程 | `nova-review/references/commit-contract.md#1-身份与分类`、`#2-豁免白名单` | 显式替换为 FEAT/PATCH/FIX/MAINT，schema 1 历史分类只读兼容，并保留更严格客观豁免 |
| L2 | 项目管理文档脚注 | `nova-review/references/commit-contract.md#2-豁免白名单` | 保留为 EX-DOC 的完整 diff 双侧路径规则 |
| L3 | 禁止主观降级 | 同上 | 保留并 fail closed |
| L4 | plan mode 前后阶段 | `nova-development/references/implementation-sop.md#6-plan-mode-追加约束` | 保留；Review 改为人工触发 |
| K1 | plan 审批后编码 | `implementation-sop.md#6-plan-mode-追加约束` | 保留 |
| K2 | 测试不得迁就代码 | `implementation-sop.md#3-编码约束` | 保留 |
| K3 | 同一失败三次停止 | `implementation-sop.md#3-编码约束` | 保留 |
| K4 | 新依赖先声明并走 pyproject | `implementation-sop.md#3-编码约束` | 保留并补充其他语言权威清单 |
| K5 | 子任务提交、失败不可提交、Review 门禁 | `implementation-sop.md#5-提交与待-review-交接`、`review-sop.md#10-pass-后边界` | 测试/精确提交保留；Review 改为提交后人工启动 |
| K6 | 实现/蓝图/设计事实边界 | `implementation-sop.md#1-准入范围与任务差异基线` | 保留 |
| K7 | 删除蓝图、保留设计锚点 | `implementation-sop.md#5-提交与待-review-交接`、`audit-contract.md#3-关闭不变量` | 显式替换为 Review PASS 后删除 |
| K8 | 任务开始固定范围与矩阵 | `implementation-sop.md#1-准入范围与任务差异基线` | 保留 |
| K9 | 待澄清禁止实施 | 同上 | 保留 |
| B1 | 编辑前记录仓库、状态、范围与既有变更 | `implementation-sop.md#1`、`review-sop.md#1` | 保留 |
| B2 | 同文件既有修改需可重建快照 | 同上 | 保留 |
| B3 | 基线保存、清理和禁止重建 | 同上、`implementation-sop.md#7-阶段完成报告` | 保留 |
| B4 | 当前任务差异排除历史未提交代码 | 同上 | 保留 |
| B5 | 无法分离时停止并让用户选择 | 同上 | 保留 |
| B6 | Review 只按当前任务差异 | `review-sop.md#1` | 保留 |
| B7 | 范围外问题只作基线风险 | 同上 | 保留 |
| B8 | 扩围前补基线/设计/验收 | 同上 | 保留 |
| P1 | 接口契约 | `implementation-sop.md#2-编码前契约` | 保留 |
| P2 | 核心不变量 | 同上 | 保留 |
| P3 | 变更闭包 | 同上 | 保留 |
| P4 | 失败语义 | 同上 | 保留 |
| P5 | 资源生命周期 | 同上 | 保留 |
| P6 | 可执行验收 | 同上 | 保留 |
| C1 | 正常和失败路径同时实现 | `implementation-sop.md#3-编码约束` | 保留 |
| C2 | 边界主动保证契约 | 同上 | 保留 |
| C3 | 跨调用边界语义一致 | 同上 | 保留 |
| C4 | 上游校验不替代权威层 | 同上 | 保留 |
| C5 | 副作用失败状态/补偿/传播 | 同上 | 保留 |
| C6 | 同步检查调用方、消费者、清理 | 同上 | 保留 |
| C7 | 禁止放宽、吞错、默认值、削断言 | 同上 | 保留 |
| T1 | 测试逐条覆盖正常/失败与跨层契约 | `implementation-sop.md#4-测试与证据复用` | 保留 |
| T2 | 设计缺陷先补契约再修实现 | 同上 | 保留 |
| E1 | 记录命令、目录和覆盖项 | 同上 | 保留 |
| E2 | 记录代码/测试/配置/依赖/环境 | 同上 | 保留 |
| E3 | 记录结果和未验证事项 | 同上 | 保留 |
| E4 | 仅相关变化、覆盖不足、失败或用户要求使证据失效 | 同上 | 保留 |
| E5 | 压缩、自检、Review、Verify、无关变化不失效 | 同上、`review-sop.md#8-证据内容标识与复用` | 保留 |
| E6 | 有效证据复用；只重跑受影响；必要时才全量 | 同上 | 保留 |
| S1 | 首次 Review 检查完整任务差异 | `review-sop.md#2-review-前自检` | 保留 |
| S2 | 范围/矩阵映射实现与证据 | 同上 | 保留 |
| S3 | 边界、并发、恢复、兼容、资源自检 | 同上 | 保留 |
| S4 | 自检修复后按失效范围重测 | 同上 | 保留 |
| S5 | 传完整差异、证据、未验证事项 | 同上 | 保留 |
| S6 | 自检未完成不得 Review；不计轮次；首次后不重建矩阵 | 同上 | 保留 |
| R0 | 编码→测试→Review→commit | `implementation-sop.md#5`、`review-sop.md#10` | 显式替换为编码→测试→commit→人工 Review |
| I1 | 完整 patch、基线标识与行块清单 | `review-sop.md#3-子代理输入角色与思考度` | 保留 |
| I2 | 意图、commit 草案、plan 摘要 | 同上 | 保留 |
| I3 | 显式 reasoning_effort | 同上 | 保留 |
| I4 | diff 标识、范围、证据 | 同上 | 保留 |
| Q1 | 契约一致性检查 | `review-sop.md#5-检查清单` | 保留 |
| Q2 | 边界/异常路径 | 同上 | 保留 |
| Q3 | 测试覆盖 | 同上 | 保留 |
| Q4 | 架构红线 | 同上 | 保留 |
| Q5 | 性能 | 同上 | 保留 |
| Q6 | 副作用 | 同上 | 保留 |
| Q7 | 代码风格 | 同上 | 保留 |
| G1 | Blocker 定义 | `review-sop.md#6-问题分级与结论` | 保留 |
| G2 | Observation-Fix 定义且默认 Fix | 同上 | 保留 |
| G3 | Observation-Defer 定义 | 同上 | 保留 |
| G4 | Defer 准入：未触及模块 | 同上 | 保留 |
| G5 | Defer 准入：公共 API 与下游 | 同上 | 保留 |
| G6 | Defer 准入：新依赖/基础设施 | 同上 | 保留 |
| G7 | Defer 准入：依赖未实现功能 | 同上 | 保留 |
| G8 | 无有效理由的 Defer 按 Fix | 同上 | 保留 |
| G9 | PASS / PASS WITH NOTES / REJECT 判定 | 同上 | 保留 |
| G10 | Blocker 必须同时满足新增和实质影响 | 同上 | 保留 |
| J1 | Reviewer 七维完整检查、一次性返回 | `review-sop.md#6` | 保留 |
| J2 | 禁止发现一项即中断 | 同上 | 保留 |
| J3 | 禁止边审边改 | `review-sop.md#3` | 保留 |
| J4 | REJECT 报告格式与行号 | `review-sop.md#6` | 保留 |
| J5 | 主代理逐条分析并统一修复 | `review-sop.md#7-reject-修复与复审` | 保留 |
| J6 | 仅失效测试重跑、Defer 入蓝图 | 同上 | 保留 |
| J7 | 修复不得扩围 | 同上 | 保留 |
| J8 | followup_task 复用原 Reviewer | 同上 | 保留 |
| J9 | 更换 Reviewer 的合法条件与轮次 | 同上 | 保留 |
| J10 | 复审逐项确认并检查修复行 | 同上 | 保留 |
| J11 | 复审不得搜索旧范围新问题 | 同上 | 保留 |
| J12 | 新问题只限修复直接触及行 | 同上 | 保留 |
| J13 | 复审附上轮报告和修复说明 | `review-sop.md#3` | 保留 |
| X1 | REJECT 必修且必须复审 | `review-sop.md#7` | 保留 |
| X2 | 最多三轮 | 同上 | 保留 |
| X3 | Reviewer 只读 | `review-sop.md#3` | 保留 |
| X4 | Reviewer 写入后失去资格 | 同上 | 保留 |
| X5 | 每轮只有提交→报告一个来回 | `review-sop.md#7` | 保留 |
| X6 | 不得跳 Review 直接 commit | `review-sop.md#10` | 显式替换为无结论不得关闭/宣称 PASS，commit 已前置 |
| X7 | 全部 Blocker/Fix 修完才复审 | `review-sop.md#7` | 保留 |
| X8 | 复审新问题范围限制 | 同上 | 保留 |
| X9 | Defer 必须附准入理由 | `review-sop.md#6` | 保留 |
| X10 | 内容标识/范围相同复用 PASS | `review-sop.md#8` | 保留 |
| X11 | 修改只使直接范围失效 | 同上 | 保留 |
| X12 | 后续不得重分级，Defer 不自动扩围 | 同上 | 保留 |
| O1 | Reviewer 不递归委派 | `review-sop.md#3` | 保留 |
| O2 | Reviewer 只读且不跑无关长任务 | 同上 | 保留 |
| O3 | spawn_agent 显式思考度 | 同上 | 保留 |
| Z1 | 按任务差异统计，10 文件/1000 行拆分，文件唯一主审 | `review-sop.md#4-大范围拆分与上下文` | 保留 |
| Z2 | 大文件分块、禁止依赖截断 | 同上 | 保留 |
| Z3 | 默认与主代理同思考度，风险集中才高一档 | `review-sop.md#3` | 保留 |
| W1 | 禁止主动 close；超时继续等终态 | `review-sop.md#9-等待终止与人工中断` | 保留 |
| W2 | turn_aborted 后同 diff 重启，最多两次 | 同上 | 保留 |
| W3 | 空响应/中间态不是 PASS | 同上 | 保留；“不可提交”改为“不可关闭/宣称 PASS” |
| F1 | 完成报告固定模板且章节不得省略 | `implementation-sop.md#7-阶段完成报告` | 保留并适配七类阶段 |
| F2 | 概要、文件、关键决策、测试、Review、蓝图、遗留 | 同上 | 保留，并新增提交/基线章节；required 未启动写“未 Review”，合法豁免写 `exempt` 和客观证据，均无 Review 轮次且不得冒充 PASS |
| F3 | L0 可省略 Review 章节 | 同上 | 显式替换为任何情况都保留；未审或 exempt 的轮次均写“不适用” |
| F4 | 相对路径与非空泛关键决策 | 同上 | 保留 |
| M1 | Plan 完整 Research→Plan→Approval→Execute→Review→Verify | `implementation-sop.md#6-plan-mode-追加约束` | Review 改人工触发，其余保留 |
| M2 | Research 读取代码/测试/配置/蓝图/工作包 | 同上 | 保留 |
| M3 | Open Questions 至少确认一次 | 同上 | 保留为确认会改变实现的决策点 |
| M4 | 计划包含关联模块 | 同上 | 保留 |
| M5 | 验收覆盖关键/异常/边界/组合 | 同上 | 保留 |
| M6 | 持久化用最终生效配置真实路径 | 同上 | 保留 |
| M7 | 完成后删除待办、保留设计锚点 | `implementation-sop.md#5`、`audit-contract.md#3` | 显式替换为 Review PASS 后关闭 |
| M8 | Execute 后强制 Review 再 Verify | `implementation-sop.md#6` | 显式替换为 Verify 报告当前 Review 状态，不自动 Review |
| M9 | Verify 只读、复用证据、不重建/扩围 | 同上 | 保留 |
