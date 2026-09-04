---
name: nova-requirements
description: 通过单问题访谈把绿地项目或新的业务需求收敛为精简的总体产品需求与可由一名全栈工程师独立交付的 REQ 需求块。用于从零项目、总体业务流程、业务模块、新需求或修改既有需求；不用于技术选型、API/数据设计、普通功能实现、局部 FIX 或 Review。
---

# Nova 需求

只定义业务要达到什么结果，不描述语言、框架、API、表、缓存、MQ、目录或实现步骤。

## 路由与有限加载

1. 首轮只检查用户表达、`.nova/PRODUCT_REQUIREMENTS.md` 的标题/总体流程/业务模块/需求索引，以及 `.nova/PROJECT_BLUEPRINT.md` 是否存在；不得扫描需求块、设计正文或代码树。
2. 无需求文档且无代码/蓝图时按绿地项目推进；由一名产品负责人先确认总体业务，再拆需求块。需求确认后转交 `nova-architecture`，不直接进入业务开发。
3. 有代码和蓝图但无需求文档时，先问是否补建；用户拒绝时不阻断普通开发。
4. 新增或改变业务结果、参与者、流程、权限、状态、规则或范围时进入本技能。已确认需求下的具体功能实现交给 `nova-development`；既有契约内局部缺陷直接交给 FIX。
5. 用户指明既有 `REQ-*` 时，只读取索引和该需求块。无法确定是需求变化还是局部实现问题时，只问一个会改变路由的问题。

## 访谈

首次提问前完整读取 [统一访谈 SOP](../nova-development/references/conversation-sop.md)，需求访谈与架构、开发保持相同的单问题、整份摘要确认和中断恢复语义。

需求阶段按统一 SOP 生成 `stageProjection`：`inheritedContracts` 只引用进入本轮需求阶段前已正式确认的总体业务范围、既有需求版本和与当前增量相关的正式业务契约，允许其真实来源阶段同为需求；`stageEvidence` 只保存本阶段查明的业务或项目事实；`stageDecisions` 只保存本阶段新增且已披露的业务候选。需求阶段不继承或写入架构选型和功能实现决定；增量证据与既有需求冲突时，在需求权威内重新确认受影响契约，无冲突内容保持有效。

绿地项目、总体需求首次访谈或用户明确重置项目范围时，第一问必须先确认目标层级：`MVP / 完整系统 / 自定义范围`。MVP 只访谈最小可用业务闭环并明确后续候选；完整系统覆盖当前目标所需的完整业务闭环、必要边界、失败恢复和验收；自定义范围以用户指定的阶段、对象或能力为边界。后续提问、明确不做和验收都受该选择约束。已有项目的增量需求沿用已确认的总体范围，只澄清当前差量；只有范围证据缺失、冲突或用户要求重置时才重新确认。

用户委托 AI 采用成熟方案时，需求阶段可免除委托范围内的逐项参数提问，但业务目标、角色、端到端流程、业务权限、业务状态、规则、范围和验收仍由需求阶段保持最终确认权。委托只产生必须披露的 AI 候选决定，不直接形成正式需求；用户修正后只重算受影响差量，整份摘要明确确认后才写入。

显式引用成熟平台、标准、最佳实践、产品或仓库，委托安全、身份、公共契约等高风险事项，或 AI 准备把某项做法作为已验证的成熟/最佳实践提出时，完整读取 [外部参考研究 SOP](../nova-development/references/reference-research-sop.md)。产品名仅作为研究例子时不得形成产品专属需求；普通低风险内部取舍只标为 AI 候选，不得声称为已验证实践，也不在需求阶段展开实现。

先收敛产品定位、角色、端到端流程、业务模块职责、关键对象生命周期、本期范围与明确不做；再按业务能力形成需求块。业务模块只用于归类，需求块才是交付单位。

需求块必须满足：一名全栈工程师能独立完成前端、后端、数据与测试；业务输入、结果和验收完整；不依赖另一个工程师同步修改才能成立。能通过稳定业务边界消除的依赖必须消除；确有共享技术契约或硬依赖时记录为架构前置，不把技术层拆成多个需求块。

## 文档与状态

创建或更新前完整读取 [需求文档规范](references/requirements-standard.md)：

- 总体契约固定为 `.nova/PRODUCT_REQUIREMENTS.md`，新建时严格使用 [总体需求模板](assets/PRODUCT_REQUIREMENTS.template.md)。
- 每个需求块固定为 `.nova/requirements/REQ-<uuidv7>_具体名称.md`，新建时严格使用 [需求块模板](assets/REQUIREMENT_BLOCK.template.md)。
- 新 Key 用 `python3 ../nova-review/scripts/nova_review.py new-requirement-id` 生成；Key 永久不变，需求块原地更新完整定义并递增版本，不创建日期副本或差量文档。
- 状态只允许 `待实现 / 开发中 / 已实现 / 已更新`。新需求为待实现；完整 delivery-plan 检查点成功后进入开发中；全部有效切片可信 PASS 后才为已实现；已实现需求的业务定义改变后为已更新。开发中时“已实现版本”和“实现依据”保留上一完整实现或同时为“无”，不得把当前未完成版本写成已实现。
- 普通规则调整只更新目标需求块和索引；只有总体流程、业务模块或项目范围改变时才更新总体章节。

首次创建需求体系时可读取 [完整示例](references/examples/equipment-rental/.nova/PRODUCT_REQUIREMENTS.md) 及其目标需求块；已有体系时不加载示例或无关需求块。

写入后运行：

```bash
python3 scripts/validate_requirements.py --index /absolute/path/to/.nova/PRODUCT_REQUIREMENTS.md
python3 scripts/validate_requirements.py --block /absolute/path/to/.nova/requirements/REQ-..._name.md
```

需求确认同时授权在上述校验通过后立即创建精确范围本地 requirement 检查点，不等待架构或开发。提交前按 `../nova-review/references/commit-contract.md` 的 requirement 契约生成 trailers，并用 `../nova-review/scripts/nova_review.py validate-message --repo ... --message-file ... --diff-file ...` 校验完整 staged diff；任一步失败不得提交或进入下游阶段。检查点不进入人工 Review，Git push、远程配置和 SVN commit 仍须独立授权。

检查点成功后判断共享边界：需要从零初始化或改变共享工程骨架、数据所有权、公共 API、事件或 Mock 时转入 `nova-architecture`；否则转入 `nova-development` 澄清具体实现。不得再次询问是否提交已确认需求，也不得把需求文件夹带进后续 Work-Item。
