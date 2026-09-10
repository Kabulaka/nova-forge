---
name: nova-architecture
description: 在总体需求确认后，以单问题访谈确定足以指导开发和并行协作的技术架构、七章项目蓝图及共享 API/数据/事件/Mock 契约。用于绿地初始化、技术栈选择、公共接口或数据所有权设计、并行开发前置准备；不用于产品需求定义、单个功能实现、局部 PATCH/FIX、ADR 或 Review。
---

# Nova 架构

目标是给开发明确、精简、可验证的公共边界；不生成选型报告、ADR 或可从代码恢复的说明。

## 准入与有限加载

1. 首轮只读取 `.nova/PRODUCT_REQUIREMENTS.md` 的总体流程、业务模块和需求索引，`.nova/PROJECT_BLUEPRINT.md` 的技术栈、模块、系统分层、跨模块契约、活动工作索引，以及存在时的 `.nova/SHARED_CAPABILITIES.md`；不得扫描全部需求块或功能设计。
2. 绿地项目在总体需求确认后必须进入本技能。已有项目只有在技术栈/系统边界未定，或目标需求引入新的共享数据、公共 API、事件、基础设施、跨需求依赖时才进入；现有蓝图和架构契约足以约束目标功能时直接交给 `nova-development`。
3. 是否需要架构确认依据开发者是否会对语言/框架/存储/通信方式、数据所有权、公共接口或共享失败语义作出不同且不兼容的选择；只是模块内部实现选择时不扩大到架构阶段。
4. 只读取受影响的需求块。无法判断时只问一个会改变公共开发边界的问题。进入架构不等于必须产出：逐项核对共享工程骨架、数据所有权、公共 API、事件和 Mock，均无真实差量时报告依据后零产物交给开发，不创建编号、文件、提交或 Review；存在真实差量时创建一个 `ARCH-*` checkpoint。ARCH 是架构身份，不是开发工作项，不进入蓝图交付工作项表；只服务单个功能的内部实现选择仍归该 FEAT。

## 访谈与决策

首次提问前完整读取 [统一访谈 SOP](../nova-development/references/conversation-sop.md)。从已确认业务场景推导技术决策，逐项解释用户可感知的成本、部署、数据、恢复和扩展影响，不要求用户在未知后果下直接选择产品名称。

架构阶段按统一 SOP 生成 `stageProjection`：`inheritedContracts` 只引用进入本阶段前已正式确认且与当前范围相关的需求，并保留其需求来源阶段；`stageEvidence` 只保存本阶段查明的技术栈、蓝图、代码、配置和外部技术事实；`stageDecisions` 只保存本阶段新增且已披露的共享架构候选。不得把需求契约复制成架构决定；架构证据与继承需求冲突时，暂停架构收敛并返回 `inheritedContracts` 标明的需求来源重新确认，不在架构阶段改写业务语义。

用户委托 AI 采用成熟方案时，架构阶段可免除委托范围内的逐项选型提问，但显著成本、部署边界、数据所有权、公共 API/事件、身份与安全边界、共享失败语义仍必须作为具体候选披露并由整份摘要确认。委托不得静默扩大基础设施或跨越已确认需求。

显式引用成熟平台、标准、最佳实践、产品或仓库，或委托安全、身份、公共契约等高风险事项时，完整读取 [外部参考研究 SOP](../nova-development/references/reference-research-sop.md)。研究事实和架构候选分开呈现；产品名仅作为研究例子时不得形成产品专属依赖。

AI 结合已确认上下文发现候选做法时，只有准备把它作为已验证的成熟/最佳实践，才进入同一研究 SOP；普通低风险模块内部取舍只标为可修正的 AI 候选，是否包含多个直接依赖边界本身不触发研究，具体实现交给 `nova-development`。

至少闭环：语言与框架、运行形态、代码结构、系统分层及目录映射、允许依赖、数据存储与所有权、公共 API、鉴权、失败恢复、部署边界，以及需求实际需要时的缓存、事件/MQ 和 Mock。没有明确需要的基础设施写为“不使用”，不创建空目录或占位文档。

架构必须主动消除需求块之间的开发依赖：共享 API、数据契约、类型和必要 Mock 先冻结；能由契约解耦的依赖不得保留。只有业务顺序本身不可消除的硬依赖才进入串行清单。

## 交付物

1. `.nova/PROJECT_BLUEPRINT.md` 保持七章精简结构；创建或修改时复用 `nova-development` 的 [蓝图规范](../nova-development/references/blueprint-standard.md)、[模板](../nova-development/assets/PROJECT_BLUEPRINT.template.md) 和校验器。
2. `.nova/architecture/ARCHITECTURE_CONTRACTS.md` 是并行门禁和架构契约索引，新建时严格使用 [架构契约模板](assets/ARCHITECTURE_CONTRACTS.template.md)。
3. 共享语言、框架、运行形态和目录边界放 `architecture/foundation/`，新建时使用 [工程骨架模板](assets/FOUNDATION_CONTRACT.template.md)；数据所有权和共享数据规则放 `architecture/data/`，使用 [数据契约模板](assets/DATA_CONTRACT.template.md)；公共 API 使用 OpenAPI，事件使用 AsyncAPI，Mock/fixture 放 `architecture/mocks/`。
4. 只创建实际需要的目录；迁移、共享类型和接口实现仍放正常源码目录。
5. `.nova/SHARED_CAPABILITIES.md` 是已实现共享能力的复用路由索引，使用 [共享能力目录模板](assets/SHARED_CAPABILITIES.template.md)；绿地或暂无能力时不创建空目录。架构负责冻结共享代码区域、分层和依赖边界，功能开发在用户确认并完成最低验收后登记实现；候选或实现若要求新增技术栈、层、共享依赖、数据所有权或公共契约，必须先完成架构确认。

创建或更新前完整读取 [架构契约规范](references/architecture-standard.md)。首次建立架构体系时可读取 [并行项目示例](references/examples/order-platform/.nova/architecture/ARCHITECTURE_CONTRACTS.md) 及其实际引用；已有体系时只读目标契约。

存在真实差量并写入后运行：

```bash
python ../nova-development/scripts/validate_blueprint.py /absolute/path/to/.nova/PROJECT_BLUEPRINT.md
python scripts/validate_architecture.py /absolute/path/to/.nova/architecture/ARCHITECTURE_CONTRACTS.md
python scripts/validate_architecture.py --ready /absolute/path/to/.nova/architecture/ARCHITECTURE_CONTRACTS.md
python scripts/validate_shared_capabilities.py --if-present /absolute/path/to/.nova/SHARED_CAPABILITIES.md
```

架构交付在提交前把需要项及对应契约标记为 `已确认`，确认依据写本次 `ARCH-*`。按提交契约生成 `arch(scope): 中文结果摘要` 和 architecture trailers，以完整 staged diff 运行仓库感知 `validate-message`；成功提交后再运行 `--ready`。`--ready` 从 Git 归属验证 ARCH、需求 checkpoint、索引行及其确认时看到的契约字节；工作树变化、未提交 ARCH、ARCH 后漂移、无关工作项或手填批次名均不能解锁。schema 1 的既有 PEND Review 架构证据仅作历史兼容。

阶段结束必须使用实施 SOP 的“架构完成报告”：先写实际结论（零差量或已形成 ARCH）和明确未改范围，再列差量依据、契约与验证、提交状态、就绪边界和下一步。发送前把候选报告写入项目外临时文件并执行 `../nova-review/scripts/nova_review.py validate-report --stage architecture --report-file ...`，失败不得发送；临时文件随后清理。零差量不得伪造空 ARCH、空文件或 Review 状态。
