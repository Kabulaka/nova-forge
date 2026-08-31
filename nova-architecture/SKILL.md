---
name: nova-architecture
description: 在总体需求确认后，以单问题访谈确定足以指导开发和并行协作的技术架构、七章项目蓝图及共享 API/数据/事件/Mock 契约。用于绿地初始化、技术栈选择、公共接口或数据所有权设计、并行开发前置准备；不用于产品需求定义、单个功能实现、局部 FIX、ADR 或 Review。
---

# Nova 架构

目标是给开发明确、精简、可验证的公共边界；不生成选型报告、ADR 或可从代码恢复的说明。

## 准入与有限加载

1. 首轮只读取 `.nova/PRODUCT_REQUIREMENTS.md` 的总体流程、业务模块和需求索引，以及 `.nova/PROJECT_BLUEPRINT.md` 的技术栈、模块、跨模块契约、活动工作索引；不得扫描全部需求块或功能设计。
2. 绿地项目在总体需求确认后必须进入本技能。已有项目只有在技术栈/系统边界未定，或目标需求引入新的共享数据、公共 API、事件、基础设施、跨需求依赖时才进入；现有蓝图和架构契约足以约束目标功能时直接交给 `nova-development`。
3. 是否需要架构确认依据开发者是否会对语言/框架/存储/通信方式、数据所有权、公共接口或共享失败语义作出不同且不兼容的选择；只是模块内部实现选择时不扩大到架构阶段。
4. 只读取受影响的需求块。无法判断时只问一个会改变公共开发边界的问题。

## 访谈与决策

首次提问前完整读取 [统一访谈 SOP](../nova-development/references/conversation-sop.md)。从已确认业务场景推导技术决策，逐项解释用户可感知的成本、部署、数据、恢复和扩展影响，不要求用户在未知后果下直接选择产品名称。

至少闭环：语言与框架、运行形态、数据存储与所有权、公共 API、鉴权、失败恢复、部署边界，以及需求实际需要时的缓存、事件/MQ 和 Mock。没有明确需要的基础设施写为“不使用”，不创建空目录或占位文档。

架构必须主动消除需求块之间的开发依赖：共享 API、数据契约、类型和必要 Mock 先冻结；能由契约解耦的依赖不得保留。只有业务顺序本身不可消除的硬依赖才进入串行清单。

## 交付物

1. `.nova/PROJECT_BLUEPRINT.md` 保持七章精简结构；创建或修改时复用 `nova-development` 的 [蓝图规范](../nova-development/references/blueprint-standard.md)、[模板](../nova-development/assets/PROJECT_BLUEPRINT.template.md) 和校验器。
2. `.nova/architecture/ARCHITECTURE_CONTRACTS.md` 是并行门禁和架构契约索引，新建时严格使用 [架构契约模板](assets/ARCHITECTURE_CONTRACTS.template.md)。
3. 共享语言、框架、运行形态和目录边界放 `architecture/foundation/`，新建时使用 [工程骨架模板](assets/FOUNDATION_CONTRACT.template.md)；数据所有权和共享数据规则放 `architecture/data/`，使用 [数据契约模板](assets/DATA_CONTRACT.template.md)；公共 API 使用 OpenAPI，事件使用 AsyncAPI，Mock/fixture 放 `architecture/mocks/`。
4. 只创建实际需要的目录；迁移、共享类型和接口实现仍放正常源码目录。

创建或更新前完整读取 [架构契约规范](references/architecture-standard.md)。首次建立架构体系时可读取 [并行项目示例](references/examples/order-platform/.nova/architecture/ARCHITECTURE_CONTRACTS.md) 及其实际引用；已有体系时只读目标契约。

写入后运行：

```bash
python3 ../nova-development/scripts/validate_blueprint.py /absolute/path/to/.nova/PROJECT_BLUEPRINT.md
python3 scripts/validate_architecture.py /absolute/path/to/.nova/architecture/ARCHITECTURE_CONTRACTS.md
python3 scripts/validate_architecture.py --ready /absolute/path/to/.nova/architecture/ARCHITECTURE_CONTRACTS.md
```

架构交付在提交前把需要项及对应契约标记为`待Review`，并把 Review 依据写为同一架构 `PEND-*`。`--ready` 只有共享工程骨架、数据所有权、所需 API/事件/Mock 契约均存在、状态一致，且所引 PEND 可从 `.nova/audit/` 验证为 Review PASS 时通过；PASS 后直接由不可变审计派生就绪，无需递归改写架构文档。通过后，各需求块才能由不同全栈工程师并行进入 `nova-development`；不得把文档状态或手填批次名伪装成 Review PASS。
