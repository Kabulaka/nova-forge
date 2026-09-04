# AI Skills 工作区 — 架构契约

> 架构契约版本：1
> 蓝图引用：../PROJECT_BLUEPRINT.md

## 1. 并行开发门禁

| 门禁 | 是否需要 | 状态 | Review 依据 |
|------|----------|------|-------------|
| 共享工程骨架 | 是 | 待Review | PEND-01a06a50-27d0-7fe5-8d30-ab9de658eaa0 |
| 数据所有权与契约 | 是 | 待Review | PEND-01a06a50-27d0-7fe5-8d30-ab9de658eaa0 |
| 公共 API 契约 | 否 | 不适用 | 无 |
| 事件契约 | 否 | 不适用 | 无 |
| Mock 与测试夹具 | 否 | 不适用 | 无 |

## 2. 契约索引

| 契约类型 | 业务范围 | 路径 | 状态 | 所有者 |
|----------|----------|------|------|--------|
| 工程骨架 | Nova 三阶段访谈 | [访谈治理工程骨架](foundation/interview-governance.md) | 待Review | 工作区治理 |
| 数据 | 委托、证据、候选与确认状态 | [访谈决策状态契约](data/interview-decision-state.md) | 待Review | 访谈治理 |
| 工程骨架 | Codex 与 Claude Code 插件分发及同会话续接 | [双宿主插件工程骨架](foundation/dual-host-plugin.md) | 待Review | 插件运行时 |
| 数据 | 本机同宿主同会话检查点 | [会话检查点数据契约](data/session-checkpoint.md) | 待Review | 状态核心 |
| 工程骨架 | 需求确认、可控任务规划、开发与 Review 交接 | [交付治理工程骨架](foundation/delivery-governance.md) | 待Review | 交付治理 |
| 数据 | 每个需求版本的独立工作项、内部里程碑和聚合进度 | [需求交付台账数据契约](data/requirement-delivery-ledger.md) | 待Review | 交付治理 |

## 3. 硬依赖

| 需求块 | 依赖需求块 | 无法解除的业务原因 | 开发顺序 |
|--------|------------|--------------------|----------|
| REQ-01a05ba8-f944-7de8-83ba-599a04745d83 | 无 | 无 | 并行 |
| REQ-01a06524-60ee-7d61-a9f1-c588cd2bfdff@v1 | 无 | 无 | 并行 |
| REQ-01a06a50-2732-704d-97d0-7a98b205a4ea@v2 | 无 | 无 | 并行 |
