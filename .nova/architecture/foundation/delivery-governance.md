# AI Skills 工作区 — 交付治理工程骨架契约

> 工程骨架契约版本：1

## 1. 技术与运行

| 语言 | 框架 | 运行形态 | 持久化 | 缓存 | 消息 | 鉴权 | 部署 |
|------|------|----------|--------|------|------|------|------|
| Markdown、严格 JSON 与 Python 3 标准库 | Nova 需求、架构、开发、Review 技能及确定性 Git 校验 | 本地命令行与宿主技能路由 | Git commit、`.nova/requirements/`、`.nova/delivery/`、蓝图和分片审计 | 只复用已验证的 commit、内容 SHA-256 与审计索引 | 不使用 | 用户整份确认、Git 当前仓库边界与 Review 明确授权 | 当前本地工作区；不执行 push 或远程写入 |

### 1.1 提交分型

| Commit-Kind | 身份与必需元数据 | 允许文件 | Review 与审计 | 下游用途 |
|-------------|------------------|----------|---------------|----------|
| `requirement` | `Nova-Schema`、`Commit-Kind: requirement`、`Requirement-Ref`、`Requirement-Path`、`Requirement-SHA256`、`Validation` | 当前需求版本对应的需求块、总体需求索引及其直接需要的总体业务段落 | 不进入人工 Review，不生成 Work-Item 完成审计 | 以 commit、逐字 Requirement-Ref 和需求块内容 SHA-256 三元组建立下游基线 |
| `delivery-plan` | `Nova-Schema`、`Commit-Kind: delivery-plan`、`Requirement-Ref`、`Requirement-Commit`、`Requirement-SHA256`、`Plan-Version`、`Validation` | 当前需求版本台账、蓝图投影及必要的需求状态行 | 不进入人工 Review，不生成 Work-Item 完成审计 | 表示需求已认领、完整需求级交付设计已持久化并进入开发中 |
| `work-item` | 现有 `Work-Item`、`Change-Class`、`Design-Ref`、`Review-Policy`、`Exemption-Rule` 和 `Validation` 契约 | PEND/FIX/MAINT 的设计、实现、测试和直接治理更新 | 只按 `Review-Policy` 选择和归档 | 交付单个切片或修复，不得代替需求与计划检查点 |
| `audit` | 现有 Review 关闭工具生成的确定性审计元数据 | 蓝图、需求状态、设计状态和 `.nova/audit/` | 记录既有 Review 结论，不再次 Review | 更新切片完成证据并从台账聚合需求状态 |

`Commit-Kind` 缺失的历史 Nova commit 继续按现有 Work-Item/Audit 规则解析；新提交一旦声明 `Commit-Kind`，必须严格匹配对应字段集合，禁止把多种 kind 混在同一提交。需求和计划检查点不得携带 `Work-Item`、`Change-Class`、`Design-Ref`、`Review-Policy`、`Exemption-Rule` 或 `Review-State`。

## 2. 目录与依赖

| 代码区域 | 职责 | 允许依赖 | 禁止依赖 |
|----------|------|----------|----------|
| `nova-requirements/` | 在整份需求确认和校验后创建独立 requirement 检查点并交付基线三元组 | 需求索引、目标需求块、Git 只读状态与需求校验器 | 等待架构或开发后夹带提交；创建 Work-Item 或 Review 候选 |
| `nova-architecture/` | 只在共享边界变化时创建架构 PEND，并要求可信 Review PASS | 已提交需求三元组、蓝图和架构契约 | 为无共享变化的需求制造架构；在 Review 前放行开发 |
| `nova-development/` | 在首个切片前生成完整台账和 delivery-plan 检查点，再一次激活一个 PEND | 已提交需求、必要且 ready 的架构、台账数据契约和设计 SOP | 只登记当前切片；静默删除后续切片；把需求级台账当作全部详细设计 |
| `nova-review/` | 只选择声明需要 Review 的 Work-Item，并在 PASS 后原子更新台账投影与需求聚合状态 | Work-Item commit、活动蓝图、台账、可信审计 | 选择 requirement/delivery-plan 检查点；单片 PASS 即关闭整个需求 |
| `.nova/delivery/` | 保存每个 `REQ@版本` 的一份权威交付台账 | 需求基线三元组、PEND 身份、蓝图和 Review 审计 | 会话状态、自由文本推断、秘密或跨项目引用 |

### 2.1 阶段门禁

| 转换 | 必须满足 | 失败行为 |
|------|----------|----------|
| 需求确认 → 已提交基线 | 整份需求用户确认；需求索引和需求块校验通过；精确范围可隔离 | 不提交、不进入架构或开发，保留上一有效版本并报告具体阻断 |
| 已提交基线 → 架构 | 共享骨架、数据所有权、公共 API、事件或 Mock 至少一项发生变化 | 无共享变化时跳过架构；有变化时创建单独架构 PEND |
| 架构 → 完整计划 | 所需架构 PEND 可从可信审计派生 Review PASS | Review 未通过时可保留规划候选，但不得提交开发中状态或激活切片 |
| 已提交基线/ready 架构 → 开发中 | 台账列出完整有效切片集合并通过交叉校验；delivery-plan 检查点提交成功 | 维持待实现，不得只创建第一个 PEND 或宣称计划已保存 |
| 开发中 → 已实现 | 全部有效 PEND 均有可信 Review PASS，当前、剩余和阻塞均为空 | 任一条件不满足时只更新进度，继续保持开发中 |

### 2.2 查询与失败恢复

进度查询只接受精确 `Requirement-Ref` 或从当前活动 PEND 唯一反查，不做模糊匹配。结果固定为 `total`、`completed`、`current`、`remaining`、`blocked`，并附 requirement commit、plan version 和证据来源。任何提交、台账、蓝图或审计不一致均失败封闭，保持上一有效投影，不从会话胶囊补齐正式状态。
