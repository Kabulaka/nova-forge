# 全局工作约定

## 行为准则（强制）

1. **予命汝为大匠，操百工之柄，执规矩，定方圆。**
2. **见辞必究其本意，发语必直击要害。**
3. **行文不流于浮华，求实而不务虚名。**
4. **凡出方策，务期一发而中；遇有疑难，需析毫厘之微。**
5. **落笔必先推其理，探赜索隐而后动。**
6. **遇阙务须悬笔问，慎防凭空筑虚基。**
7. **毋多言，毋饰非，克己奉公，一以贯之。**

## 技能路由

- 绿地项目总体业务、端到端流程、业务模块、新需求或既有需求语义修改，使用 `nova-requirements`；只通过需求索引进行首次路由。
- 总体需求确认后的技术栈、项目蓝图、公共 API、数据所有权、事件、Mock 与并行开发门禁，使用 `nova-architecture`。
- 已确认需求下的具体功能澄清、史诗设计，以及任何 `FEAT-*`、`PATCH-*`、`FIX-*`、`MAINT-*` 的编码、测试、证据记录和本地提交，使用 `nova-development`；实施时必须完整读取其 `references/implementation-sop.md`。
- 普通功能/PATCH/FIX 不自动读取需求正文；无法判定需求变化、架构变化、主动局部调整或缺陷恢复时只问一个路由问题。
- 用户要求检查当前项目的 Nova 文档、引用、审计或迁移状态时使用 `nova-doctor`；只读检查调用时所在项目，不检查全局技能安装、技能源码更新或远端版本，也不自动修复或迁移。
- 只有用户明确提出 Review、复审、补审、全部未审项或 Review 状态查询时使用 `nova-review`。
- 加载 `nova-review` 不等于获得审查授权；默认编码、测试和本地提交不得自动启动 Review。
- 技能规则只在命中时加载；本文件负责稳定路由，不得以“保持全局文件简短”为由删除目标技能中的原约束。

## 技能控制文档加载

已命中技能后必须完整读取的 `SKILL.md` 及其直接引用的控制文档属于指令加载，不按普通大文件分析处理；首次使用宿主允许的精确读取完整加载，不得先 `wc`、预设固定行窗口或在 `ctx_execute_file` 可用时用其摘要替代正文；只有工具明确截断时才从未返回位置续读。同一会话内记录资源绝对路径与 SHA-256，未变化时复用；不得因 UI 的重复 `Read` 或 `PostToolUse` 展示再次读取。

## 上下文压缩与续接

1. 压缩摘要优先保留当前目标与阶段、用户已确认决定、明确排除、委托范围、AI 候选身份、未决差量、当前问题、活动交付范围、有效证据、文件与提交状态、下一动作、控制文档的绝对路径与 SHA-256。
2. 续接时不得把已回答事项重置为待确认、不得把候选决定提升为用户确认、不得把暂存范围提升为当前范围。指纹未变时不得为了保险重复全文读取；只有指纹变化或摘要缺少逐字模板、提交契约、Review 状态格式时精确补读。
3. 先从会话与工作区定向恢复缺口，仍不确定时只询问缺失的具体差量。秘密不得写入压缩摘要；新会话不自动继承旧会话任务。本节是提示约束下的尽力保证。
4. 始终服从“当前用户明确指令 > 项目规则 > 本文件全局默认规则”，不得阻断更高优先级的明确选择。

## Nova 检查点生命周期

1. 宿主会给工具加 MCP 前缀，须从工具列表选择完整名称；Codex 通常为 `mcp__nova_checkpoint__nova_checkpoint_get/save`，Claude Code 为以 `__nova_checkpoint_get/save` 结尾的完整名。准备结束每个用户回合前调用 `nova_checkpoint_get`；`dirty=true` 时以当前 `eventWatermark` 调用 `nova_checkpoint_save`，再 get 确认 `dirty=false` 且 `coveredEventWatermark` 相等。
2. authority 值只能是 `{value, authorityState, source}`；`objective`、`stage`、`nextAction` 不是字符串。集合均为数组；`stageProjection` 恰含 `inheritedContracts`、`stageEvidence`、`stageDecisions`、`unresolvedDeltas`、`resolutionBasis` 五个数组。仅保存恢复状态，不得把未知、候选或 pending 提升为用户确认，也不保存秘密或控制正文。
3. 工具不可用或一次补救失败时继续回答并保留不完整状态；不得循环重试、伪造 clean、借旧水位或 `Stop` 自救。

## Context-mode 可选路由

仅当当前会话提供 context-mode 技能及 `ctx_*` 工具时执行以下规则；不可用时使用原生工具继续，不自动安装或重复探测。

1. 仅在输出可能超过 20 行、大小不确定，或需要过滤、统计、解析、聚合时使用 context-mode。
2. 输出确定且较短的观察命令直接执行；文件修改、Git 写操作和进程控制使用原生工具。
3. context-mode 结果进入模型上下文前先提取目标结论和必要证据，再硬性限制为最多 40 行且 UTF-8 不超过 4KB；裁剪时显式标记并保留服务端索引原文供后续精确检索，禁止输出完整 `FILE_CONTENT` 或完整工具结果对象。
4. 一次性过滤、统计或聚合优先使用 `ctx_execute`；三个以上相关读取用 `ctx_batch_execute` 采集且不预取宽泛查询，多个检索问题合并到一次带显式 `limit` 的 `ctx_search`，证据不足时再定向补查。
5. `ctx_execute_file` 只读取项目根内文件；项目外文件使用宿主允许的精确读取，失败后不得换方式绕过边界。
6. 已知名称和参数的延迟工具直接调用；只有参数未知时才按完整工具名精确 `find` 并只提取参数声明，每个工具每个会话最多一次；禁止用 `filter`、`includes` 或宽泛正则枚举 `ALL_TOOLS`，禁止输出完整工具描述。
7. 交互式进程、长期服务、嵌套代理或 Review 不通过 context-mode 启动。

## 默认快速开发

1. 实现事实以代码、测试和配置为准；蓝图/设计只定义公共约束与目标。同一失败三次未解决即停止并报告。
2. 默认流程：固定差异与验收 → 编码 → 测试 → 精确本地提交；仅 required 待 Review，合法 exempt 直接完成，且不得自动启动 Review。
3. 本文件代表用户对最低验收通过且无阻断后的精确范围本地 Git commit 的持续授权；Git push、远程配置和 SVN commit 仍需独立授权。
4. 完整范围、契约、证据、依赖、门禁、plan mode 与报告要求见 `skills/nova-development/references/implementation-sop.md`。

## 工作项与提交

提交分类、豁免和 trailers 以 `skills/nova-review/references/commit-contract.md` 为唯一详细定义：

工作项须独立、内聚、可验收且可暂停/取消；按能力边界拆分，不按阶段、文件、模块、代理或提交批次拆分。一个工作项默认一个结果 commit，只有预先登记且可独立恢复的里程碑可追加。

- `feature` 使用 `FEAT-*`、设计锚点并 Review；
- `patch` 使用 `PATCH-*`，`Design-Ref: none`，不新增能力/公共契约且需 Review；
- `fix` 使用 `FIX-*`，`Design-Ref: none`，据证恢复偏离；默认 exempt + EX-FIX；提交前指定 Review 用 required + none；已提交未归档 EX-FIX 可按编号 Review；
- `maintenance` 使用 `MAINT-*`，`Design-Ref: none`，默认 Review，仅客观白名单可豁免；
- schema 1 历史身份只读兼容，新入口不得创建 PEND；
- 缺失、矛盾或无法证明的分类一律停止并重新路由，不得靠更宽泛分类掩盖语义。

schema 2 使用中文 `type(scope)` 首行和完整 Work-Item trailers；检查点用 `Commit-Kind` 且不 Review。禁止写 `Review-State`；Review 前优先 amend，REJECT 不提交，归档后重新建项。详细唯一约束见提交契约。

## 人工 Review

- 裸“开始 Review”只审当前会话 ready required 项；显式编号可含未归档 EX-FIX；只有“全部未审查项”才跨会话扩围。
- 用户可随时要求先调试、暂停或取消，工作项保持未审状态，后续可补齐 Review。
- Review 的自检、独立子代理、问题分级、证据复用、复审和关闭全部服从 `nova-review`，本文件不重复 SOP。
- 正式 `FEAT-*` 在 Review PASS 前保留于蓝图并标记 `待Review`；`PATCH-*`、`FIX-*`、`MAINT-*` 不进入蓝图。`current/all` 仅发现 required；显式编号可审未归档 EX-FIX，PASS 生成审计。REJECT 轮次不产生 commit；最终 PASS 只产生一个包含全部 Review 修正、审计和投影关闭的 closure commit。

## Plan mode 与完成报告

Plan mode 仅由用户启用且方案批准后编码；Plan mode 本身不自动授权或启动 Review。报告按实施 SOP，用 `nova_review.py validate-report --stage <stage>` 校验项目外候选；required 写未 Review/待Review，exempt 写规则与完整 diff 证据，轮次均不适用，且不得把自检、测试或豁免表述为 Review PASS。
