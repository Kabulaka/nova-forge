# AI Skills 工作区 — 需求交付台账数据契约

> 数据契约版本：1
> Contract-Key：DATA-REQUIREMENT-DELIVERY-LEDGER-01
> 所有者：交付治理

## 1. 所有权

| 数据对象 | 权威写入方 | 允许读取方 | 禁止行为 |
|----------|------------|------------|----------|
| 需求基线三元组 | `nova-requirements` 在用户整份确认、校验和 requirement commit 成功后写入 | 架构、开发、Review 与交付治理校验器 | 从未提交工作树、会话状态或模糊 Git 历史推断基线 |
| 需求版本交付台账 | `nova-development` 通过确定性工具创建；后续由交付计划或 Review 原子更新 | 需求、开发、Review 技能与进度查询 | 各技能维护副本、物理删除历史任务或里程碑、绕过 plan_version |
| 蓝图未完成投影 | 交付治理从同一候选台账确定性生成并与台账同提交 | 路由、开发、Review 和用户 | 把蓝图投影反向当作完成权威或只投影当前任务 |
| 任务完成证据 | `nova-review` 的可信批次、年度功能行和哈希索引 | 交付治理聚合器与审计查询 | 由台账字段、内部里程碑、commit message 或会话声明自证 Review PASS |

## 2. 数据约束

| 字段或关系 | 类型或范围 | 不变量 | 兼容规则 |
|------------|------------|--------|----------|
| 文件路径 | `.nova/delivery/<Requirement-Key>_v<正整数>.json` | 每个 `REQ@版本` 恰好一份普通文件，UTF-8、结尾换行、两空格缩进和稳定 key 顺序 | 未知路径、符号链接、非普通文件或跨目录引用拒绝 |
| `schema` | 正整数，首版为 1 | 未知 schema 拒绝读写，不用默认值补齐 | 只有确定性迁移器可升级旧版本 |
| `requirement_ref` | 规范 `REQ-{uuidv7}@vN` | 始终逐字匹配本文件 `requirement_checkpoint` commit 中的需求索引和需求块；只有当前活动台账额外匹配工作树当前需求版本与蓝图有效任务 | 新需求版本使用新文件；旧版本继续按自身 checkpoint 校验和查询，不覆盖也不要求匹配新版本索引 |
| `requirement_checkpoint` | commit、path、sha256 对象 | commit 是当前仓库 ancestor 中合法 requirement commit，path 和 sha256 与该 commit 中需求块字节一致 | 历史提交没有合法 kind 时不得伪造迁移 |
| `plan_version` | 从 1 开始的台账修订正整数 | 任何任务集合、内部里程碑、依赖、完成定义、设计引用、状态或阻塞变化均严格递增且追加一个对应 change | 相同上一版本、规范化候选与幂等键复用既有版本 |
| `status` | `development` 或 `implemented` | development 要求存在未完成有效任务；implemented 要求所有有效任务可信 PASS 且当前、剩余、阻塞为空 | 本需求 bootstrap 在机制落地时直接迁移为一项活动任务 |
| `work_items[].work_item` | 唯一规范 `PEND-{uuidv7}` | 同台账和全仓库唯一稳定，归档、替代或取消后不得复用；每项必须满足独立、内聚、可控边界 | 既有合法数字 PEND 只读兼容，不用于新任务 |
| `work_items[].dependencies` | 同台账 PEND 或已 PASS 外部 PEND 数组 | 依赖无环，未满足时不得 active | 顺序变化规范化后不改变语义 |
| `work_items[].done_definition` | 非空可执行结果 | 必须描述独立完整交付结果，不接受过程步骤、待定或同义占位 | 措辞调整只有语义不变时可保留工作项 |
| `work_items[].design_ref` | null 或稳定设计锚点 | planned 可为 null；active、review_pending、blocked、completed 必须为通过校验的已确认设计 | 设计演进使用稳定锚点和既有演进规则 |
| `work_items[].state` | planned、active、review_pending、blocked、completed、superseded、cancelled | `active/review_pending/blocked` 合计最多一个；completed 只从可信 Review PASS 派生 | 新状态需要 schema 升级和聚合正反用例 |
| `work_items[].blocked_reason` | null 或非空具体原因 | blocked 时必填，其他状态为 null | 解除阻塞必须留下 change 记录 |
| `work_items[].supersedes` | 同台账历史 PEND 数组 | 只用于经独立性校验后的任务拆分、合并或替代，不得成环 | 原任务保留为 superseded/cancelled |
| `work_items[].milestones` | 非空有序数组 | `M-<正整数>` 在任务内唯一；每项含标题、可执行完成定义、planned/active/blocked/completed 状态和提交证据；不形成 Work-Item 或 Review 身份 | 任务关闭前全部有效里程碑必须 completed，调整必须留痕 |
| `changes` | 与 plan_version 一一对应的对象数组 | 完整记录 created、added、split、merged、replaced、reordered、dependencies-updated、done-definition-updated、design-bound、activated、milestone-updated、review-submitted、blocked、unblocked、completed、cancelled；既有记录不删除不改写 | 每次修订恰有一个 change；未知 kind 或跳号拒绝，扩展需 schema 升级 |

### 2.1 Schema 1

```json
{
  "schema": 1,
  "requirement_ref": "REQ-<uuidv7>@v1",
  "requirement_checkpoint": {
    "commit": "<40-or-64-lower-hex>",
    "path": ".nova/requirements/REQ-<uuidv7>_<name>.md",
    "sha256": "<64-lower-hex>"
  },
  "plan_version": 1,
  "status": "development",
  "work_items": [
    {
      "work_item": "PEND-<uuidv7>",
      "title": "<non-empty>",
      "dependencies": [],
      "done_definition": "<executable result>",
      "design_ref": null,
      "state": "planned",
      "blocked_reason": null,
      "supersedes": [],
      "change_reason": "initial-plan",
      "milestones": [
        {
          "id": "M-01",
          "title": "<non-empty>",
          "done_definition": "<executable result>",
          "state": "planned",
          "blocked_reason": null,
          "evidence": []
        }
      ]
    }
  ],
  "changes": [
    {
      "plan_version": 1,
      "kind": "created",
      "work_items": ["PEND-<uuidv7>"],
      "reason": "initial-plan"
    }
  ]
}
```

文件使用 UTF-8、结尾换行、两空格缩进和稳定 key 顺序；未知字段、重复 key、符号链接、非普通文件、跨目录路径或非规范 UUIDv7 一律拒绝。

### 2.2 聚合与投影

有效任务为 state 不属于 `superseded`、`cancelled` 的记录。工作项 `completed` 只能从该 work item 的可信 Review PASS 派生；内部里程碑 completed 只表示阶段证据齐备，不能关闭任务或替代 Review。

| 输出 | 计算规则 |
|------|----------|
| `total` | 当前有效任务数 |
| `completed` | 有可信 Review PASS 的有效任务数 |
| `current` | state 为 active、review_pending 或 blocked 的任务；默认至多一个，并显示任务状态及其里程碑 total、completed、current、remaining、blocked |
| `remaining` | 有效且非 completed、非 current 的任务，按依赖拓扑和登记顺序稳定排列 |
| `blocked` | 当前任务或其当前里程碑的阻塞及原因；没有时为“无” |

`status=development` 要求 `total > 0` 且 `completed < total`；`status=implemented` 要求 `completed = total`、`total > 0` 且 current、remaining、blocked 都为空。蓝图必须投影全部未完成有效任务；当前任务的内部里程碑只在台账和进度查询展示。台账、蓝图和需求索引任一不一致时普通校验失败。

任务状态只允许：`planned → active`；`active → review_pending`；`active/review_pending → blocked`；`blocked → active`；`review_pending → completed` 仅由可信 Review PASS 触发；planned 或 current 任务只有在业务范围等价且新边界独立性校验通过的计划变化中才能转为 superseded/cancelled。里程碑状态只允许 `planned → active → completed`、`active → blocked → active`，同一任务至多一个 active/blocked 里程碑，任务进入 review_pending 前全部有效里程碑必须 completed。激活任务前存在任一 current 时拒绝。

### 2.3 本需求 bootstrap 台账

`REQ-01a06a50-2732-704d-97d0-7a98b205a4ea@v2` 落地 schema 1 时，保留已归档架构 PEND 为历史证据，把三个未归档开发候选收敛为一个活动工作项；原候选没有提交或审计身份，不作为已登记历史任务写入台账。

| 工作项 | 独立交付结果 | 内部里程碑 | 完整依赖 | 迁移状态 |
|--------|--------------|------------|----------|----------|
| PEND-01a06a50-27d0-7fe5-8d30-ab9de658eaa0 | 需求基线、可控任务台账、状态聚合、技能流程和端到端验证整体可用 | M-01 需求检查点与状态门禁；M-02 完整台账与最终聚合；M-03 技能流程、进度报告与端到端验证 | PEND-01a06a50-2783-78bb-9fd4-c79347c4b6e6 Review PASS | review_pending |

## 3. 一致性与并发

| 场景 | 原子边界 | 并发结果 | 幂等规则 |
|------|----------|----------|----------|
| 创建初始台账 | 锁定 requirement checkpoint、候选台账、蓝图投影和需求状态的同一 Git 基线后一次提交 | 任一文件或 HEAD 漂移整次拒绝，不形成开发中状态 | 相同基线、候选字节和幂等键返回既有 delivery-plan commit |
| 调整交付计划 | 重读上一有效 plan commit，校验历史保留、依赖、范围等价和新投影后一次提交 | 并发 plan_version 只允许基于最新版本的一个候选成功 | 相同上一版本和规范化候选只产生一个新 plan_version |
| 激活任务或里程碑 | 同时校验依赖、current 总数、设计确认指纹、蓝图引用和里程碑状态 | 已有任一 current 或依赖状态变化时拒绝旧候选 | 重复激活同一 work item/里程碑不增加版本或重复当前项 |
| Review PASS 聚合 | 在现有审计关闭锁内同时写审计、设计状态、台账状态、蓝图投影和需求索引 | 字节漂移或并发关闭整次失败，不产生部分完成 | 同一批次与 commit 集重复关闭返回既有审计结果 |
| 查询进度 | 从同一 commit 快照读取台账、蓝图和审计索引 | 读取中 HEAD 变化则重试一次最新快照，仍漂移时失败 | 相同 commit 与 Requirement-Ref 返回逐字等价五项进度 |

### 3.1 计划变化与范围保护

新增、重排、依赖调整、完成定义等价修订、激活、设计绑定、里程碑变化、提交 Review、完成、阻塞变化以及不改变业务验收且通过任务独立性校验的拆分、合并或替代都升级 plan_version，并追加与该转换逐字匹配的受限 kind。原任务必须保留为 superseded/cancelled，changes 记录原因和新旧身份；禁止从数组物理删除。仅按流程阶段、文件、模块、技能、代理或提交批次拆分的候选必须拒绝，改写为同一任务内部里程碑。

`dependencies-updated` 必须保存目标 work item、变更前后完整依赖数组和非空原因；变更前数组必须逐字匹配上一版本，变更后必须通过身份、Review 状态和无环校验。`done-definition-updated` 必须保存目标 work item、变更前后完整定义及非空等价性依据。`milestone-updated` 必须保存任务、里程碑、前后状态、证据和原因，不得改变工作项身份或把里程碑计为 Review PASS。无法证明任务完成定义等价时必须按新增/替代任务处理；涉及业务验收变化时返回需求阶段升级版本。

校验器必须比较上一有效 plan commit 与候选：若有效完成定义的业务结果减少、弱化或无法证明等价，则拒绝 delivery-plan 更新，并要求回到需求阶段创建同一 REQ 的新版本。旧版本台账保持可读，不能被新版本覆盖。

### 3.2 原子写入

计划写入先验证 requirement checkpoint、适用架构门禁、完整任务与里程碑、依赖无环、身份唯一、蓝图投影和状态聚合，再以同一精确范围本地 commit 固化。任一步失败不产生部分检查点，不改变需求状态，不激活任务。Review PASS 更新必须在现有审计原子关闭流程内同时写台账投影；并发或字节漂移时整次拒绝并重试最新基线。

## 4. 失败与恢复

| 失败点 | 对外结果 | 恢复或补偿 | 责任方 |
|--------|----------|------------|--------|
| requirement checkpoint 缺失、不是 ancestor、字段混合或内容指纹失配 | 拒绝创建或读取台账，不进入开发中 | 恢复上一合法需求检查点；当前需求重新校验并精确提交 | 需求治理与交付治理 |
| 独立架构变化没有可信 Review PASS，或同任务架构门禁被其他任务消费 | 可保留未提交规划候选，不宣称架构 ready | 完成独立架构 PEND Review，或把同任务门禁限制在唯一 PEND 后重新验证 | 架构治理 |
| 台账 schema、任务边界、里程碑、身份、依赖或完成定义非法 | 整份计划拒绝，不形成部分任务登记 | 修正候选并重新执行完整校验；不得只提交首个合法任务或把流程步骤升级为 PEND | 开发交付 |
| 蓝图投影与台账不一致或写入中并发漂移 | 整个 delivery-plan/audit 更新失败，上一投影保持有效 | 基于最新 commit 重建台账与蓝图后原子重试 | 交付治理 |
| Review 审计缺失、伪造或与 work item 不一致 | 任务不计 completed，需求保持开发中 | 由 Review 流程补齐可信审计，不接受里程碑、文档或会话声明替代 | Review 治理 |
| 计划变化物理删除历史或减少业务验收 | 拒绝新计划版本 | 恢复原台账；技术变化保留替代关系，业务变化返回需求阶段升级版本 | 交付治理与需求治理 |
| 进度查询无法唯一定位需求或证据冲突 | 返回明确失败，不输出推测进度 | 要求精确 Requirement-Ref，修复持久化冲突后重查 | 交付治理 |
