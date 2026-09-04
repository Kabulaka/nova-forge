# AI Skills 工作区 — 交付治理工程骨架契约

> 工程骨架契约版本：2

## 1. 技术与运行

| 语言 | 框架 | 运行形态 | 持久化 | 缓存 | 消息 | 鉴权 | 部署 |
|------|------|----------|--------|------|------|------|------|
| Markdown、严格 JSON 与 Python 3 标准库 | Nova 需求、架构、开发、Review、Doctor 技能及确定性 Git 校验 | 本地命令行与宿主技能路由 | Git commit、`.nova/requirements/`、`.nova/architecture/`、`.nova/delivery/`、蓝图和分片审计 | 只复用已验证的 commit、内容 SHA-256 与审计索引 | 不使用 | 用户整份确认、Git 当前仓库边界与 Review 明确授权 | 当前本地工作区；不执行 push 或远程写入 |

### 1.1 提交分型

| Commit-Kind | 身份与必需元数据 | 原子边界 | Review 与审计 | 下游用途 |
|-------------|------------------|----------|---------------|----------|
| `requirement` | `REQ-*`；`Nova-Schema: 2`、Requirement-Ref、路径、内容 SHA-256 与 Validation | 当前需求块、总体需求索引及其直接需要的总体业务段落 | 不进入人工 Review，不生成工作项审计 | 以 commit、逐字 Requirement-Ref 和需求块 SHA-256 保存确认基线 |
| `architecture` | `ARCH-*`；`Nova-Schema: 2`、Architecture-Ref、Requirement-Ref 与 Validation | 只含本次真实共享架构差量及使契约可确定校验的直接治理更新 | 不进入交付工作项表；无差量时连编号、文件和提交都不创建 | 保存已确认的共享工程骨架、数据所有权、公共 API、事件或 Mock 差量 |
| `delivery-plan` | `Nova-Schema: 2`、Requirement-Ref、可信需求三元组、Plan-Version 与 Validation | 当前需求版本台账、蓝图投影、必要的需求状态行及台账逐字绑定的设计 | 不进入人工 Review，不生成工作项审计 | 一次性登记完整 FEAT 列表和内部里程碑并进入开发中 |
| `work-item` | `FEAT-* / PATCH-* / FIX-* / MAINT-*`；Change-Class、Design-Ref、Review-Policy、Exemption-Rule 与 Validation | 默认一个完整实现结果提交；只有台账中真实内部里程碑需要独立恢复点时才可追加同编号提交 | required 项实现后待Review；合法 MAINT 豁免直接完成 | 交付独立、内聚、可暂停和可验收的能力、局部调整、缺陷恢复或维护结果 |
| `review` | `Nova-Audit-Schema: 2`、Review-Batch、Manifest-SHA256、Review-Fix-SHA256 与 Validation | REJECT 轮次零提交；最终 PASS 将全部 Review 修正和确定性审计一次提交 | 一个 Review 批次只形成一个闭环提交；提交哈希不写入自身审计内容 | 关闭目标工作项并更新蓝图、设计、台账和需求聚合状态 |

`Nova-Schema: 1` 与 `Nova-Audit-Schema: 1` 的不可变历史继续只读验证；仓库出现首个 schema 2 提交后，所有新提交必须使用 schema 2。`Commit-Kind` 缺失的历史提交继续按旧 Work-Item 规则读取。任何新提交都不得混合 checkpoint、work-item、review 或可变 `Review-State` 字段。

提交首行统一为 `type(scope): 中文结果摘要`。type 表示提交性质；scope 只取 `requirements / architecture / delivery / review / doctor / plugin / discovery / release` 中覆盖整个原子提交的最小稳定能力域，不使用任务编号、状态、文件名或 `all / misc / core / governance`。

## 2. 目录与依赖

| 代码区域 | 职责 | 允许依赖 | 禁止依赖 |
|----------|------|----------|----------|
| `nova-requirements/` | 在整份需求确认和校验后创建独立 requirement 检查点并交付基线三元组 | 需求索引、目标需求块、Git 只读状态与需求校验器 | 等待架构或开发后夹带提交；创建交付工作项或 Review 候选 |
| `nova-architecture/` | 判断共享边界是否存在真实差量；有差量时以 ARCH 固化，无差量零产物通过 | 已提交需求三元组、蓝图和架构契约 | 为进入阶段而制造文件、ARCH 或提交；把 ARCH 写进交付工作项表 |
| `nova-development/` | 首项开始前生成完整 schema 2 台账，再激活一个 FEAT；PATCH/FIX/MAINT 只处理既有契约内局部结果 | 已提交需求、适用 ARCH、台账数据契约和设计 SOP | 只登记当前任务；把流程、文件、模块、技能、代理或提交批次拆成 FEAT；以 PATCH/FIX 偷渡新能力或公共契约 |
| `nova-review/` | 选择 required 工作项，累积 REJECT 修正，并在最终 PASS 时一次提交修正与审计闭环 | 工作项实现 commit、未提交 Review 修正、活动投影、台账与可信审计 | REJECT 一轮一提交；选择 requirement/delivery-plan；把内部里程碑当作独立审查对象 |
| `nova-doctor/` | 只读诊断提交 schema、分类、首行、ARCH、蓝图投影、台账、Review 闭环及历史兼容 | 当前项目 Git 历史和 `.nova/`，各权威校验器 | 自动修复、迁移、Review、提交或检查全局安装 |
| `.nova/delivery/` | 保存每个 `REQ@版本` 的一份权威交付台账 | 需求基线三元组、FEAT 身份、蓝图和 Review 审计 | PATCH/FIX/MAINT、会话状态、自由文本推断、秘密或跨项目引用 |

### 2.1 阶段门禁

| 转换 | 必须满足 | 失败行为 |
|------|----------|----------|
| 需求确认 → 已提交基线 | 整份需求用户确认；需求索引和需求块校验通过；精确范围可隔离 | 不提交、不进入下游，保留上一有效版本并报告具体阻断 |
| 已提交基线 → 架构结论 | 明确核对共享工程骨架、数据所有权、公共 API、事件和 Mock | 无差量时报告依据并零产物通过；有差量时创建一个 ARCH checkpoint |
| 架构结论 → 完整计划 | 无差量依据明确，或所需 ARCH 已提交且当前契约校验通过 | 证据不足时不得创建或激活 FEAT，也不得为了过门禁制造 ARCH |
| 完整计划 → 开发中 | schema 2 台账列出全部 FEAT、内部里程碑、依赖、完成定义与 Requirement-Ref，并以 delivery-plan 原子提交 | 维持待实现，不得只登记首项或宣称计划已保存 |
| 实现 → 待Review | 完整结果和最低验收通过；默认形成一个 work-item commit；蓝图状态投影为待Review | 未通过时不提交、不伪造 Review 状态；内部里程碑只有客观恢复价值时才允许多提交 |
| 待Review → 已完成 | 最终 PASS 覆盖实现提交与全部未提交 Review 修正；一个 closure commit 同时保存修正、审计和投影更新 | REJECT 只修正和复验；任一漂移或校验失败均不提交、不部分关闭 |
| 开发中 → 已实现 | 当前需求版本全部有效 FEAT 均有可信 PASS，且当前、剩余和阻塞为空 | 任一条件不满足时只更新进度，需求保持开发中 |

### 2.2 查询与失败恢复

进度查询只接受精确 `Requirement-Ref` 或从当前活动 FEAT 唯一反查，不做模糊匹配。结果固定为任务级 `total`、`completed`、`current`、`remaining`、`blocked`，并在 current 中显示内部里程碑进度，同时附 requirement commit、plan version 和证据来源。任何提交、台账、蓝图、报告或审计不一致均失败封闭，保持上一有效投影，不从会话胶囊补齐正式状态。
