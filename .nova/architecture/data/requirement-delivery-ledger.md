# AI Skills 工作区 — 需求交付台账数据契约

> 数据契约版本：2
> Contract-Key：DATA-REQUIREMENT-DELIVERY-LEDGER-01
> 所有者：交付治理

## 1. 所有权

| 数据对象 | 权威写入方 | 允许读取方 | 禁止行为 |
|----------|------------|------------|----------|
| 需求基线三元组 | `nova-requirements` 在用户整份确认、校验和 requirement commit 成功后写入 | 架构、开发、Review、Doctor 与交付校验器 | 从未提交工作树、会话状态或模糊 Git 历史推断基线 |
| 需求版本交付台账 | `nova-development` 通过确定性工具创建；后续由 delivery-plan 或 Review 闭环原子更新 | 需求、开发、Review、Doctor 与进度查询 | 各技能维护副本、物理删除历史任务或绕过 plan_version |
| 蓝图活动投影 | 交付治理从同一候选台账确定性生成并与台账同提交 | 路由、开发、Review、Doctor 和用户 | 把投影当作完成权威、显示 ARCH/PATCH/FIX/MAINT，或为“开发中”制造额外状态 |
| 任务完成证据 | `nova-review` 的可信批次、年度功能行和哈希索引 | 交付聚合器、Doctor 与审计查询 | 由台账状态、里程碑、commit message 或会话声明自证 Review PASS |

## 2. 数据约束

| 字段或关系 | 类型或范围 | 不变量 | 兼容规则 |
|------------|------------|--------|----------|
| 文件路径 | `.nova/delivery/<Requirement-Key>_v<正整数>.json` | 每个 `REQ@版本` 恰好一份普通文件，UTF-8、结尾换行、两空格缩进和稳定 key 顺序 | 未知路径、符号链接、非普通文件或跨目录引用拒绝 |
| `schema` | 当前为 2 | schema 2 只允许 FEAT；未知 schema 拒绝读写 | schema 1 与其中 PEND 只读兼容，不得用旧 schema 创建新计划 |
| `requirement_ref` | 规范 `REQ-{uuidv7}@vN` | 逐字匹配 `requirement_checkpoint`、需求索引、需求块和蓝图链接 | 新版本使用新文件；旧版本继续绑定自身 checkpoint |
| `requirement_checkpoint` | commit、path、sha256 对象 | commit 是当前仓库 ancestor 中唯一合法 requirement commit，路径和摘要与该 commit 字节一致 | 历史提交没有合法 kind 时不得伪造迁移 |
| `plan_version` | 从 1 开始的正整数 | 任务集合、依赖、完成定义、设计引用、状态、阻塞或里程碑变化必须递增并追加一个 change | 相同上一版本、规范化候选与幂等键复用既有版本 |
| `status` | `development` 或 `implemented` | development 存在未完成有效 FEAT；implemented 要求全部有效 FEAT 可信 PASS | 旧 schema 1 仍按原聚合读取 |
| `work_items[].work_item` | 唯一规范 `FEAT-{uuidv7}` | 同台账和全仓库唯一稳定；归档、替代或取消后不得复用 | schema 1 的合法 `PEND-*` 保持原编号、引用和审计 |
| `work_items[].dependencies` | 同台账 FEAT 或可信 PASS 的外部工作项数组 | 依赖无环，未满足时不得 active | 顺序规范化不改变语义；不得写无上下文“待澄清” |
| `work_items[].done_definition` | 非空可执行结果 | 描述独立完整交付结果，不接受过程步骤、占位或仅按文件/阶段拆分 | 无法证明结果等价时创建替代任务或返回需求升级 |
| `work_items[].design_ref` | null 或稳定设计锚点 | planned 可为 null；active、review_pending、blocked、completed 必须绑定已确认设计 | 设计演进保持稳定锚点与历史来源 |
| `work_items[].state` | planned、active、review_pending、blocked、completed、superseded、cancelled | active/review_pending/blocked 合计最多一个；completed 只从可信 PASS 派生 | 蓝图不逐字暴露内部状态，只投影三种最小状态 |
| `work_items[].milestones` | 非空有序数组 | `M-<正整数>` 在任务内唯一；里程碑无独立 Work-Item 或 Review 身份 | 只有真实可恢复阶段才允许据此为同一 FEAT 追加实现提交 |
| `changes` | 与 plan_version 一一对应的对象数组 | 只用受限 kind，完整保留任务与里程碑演进，不删除旧记录 | 未知 kind 或跳号拒绝；扩展需要 schema 升级 |

### 2.1 Schema 2

```json
{
  "changes": [
    {
      "kind": "created",
      "plan_version": 1,
      "reason": "initial-plan",
      "work_items": [
        "FEAT-<uuidv7>"
      ]
    }
  ],
  "plan_version": 1,
  "requirement_checkpoint": {
    "commit": "<40-or-64-lower-hex>",
    "path": ".nova/requirements/REQ-<uuidv7>_<name>.md",
    "sha256": "<64-lower-hex>"
  },
  "requirement_ref": "REQ-<uuidv7>@v1",
  "schema": 2,
  "status": "development",
  "work_items": [
    {
      "blocked_reason": null,
      "change_reason": "initial-plan",
      "dependencies": [],
      "design_ref": null,
      "done_definition": "<independently executable result>",
      "milestones": [
        {
          "blocked_reason": null,
          "done_definition": "<recoverable internal result>",
          "evidence": [],
          "id": "M-01",
          "state": "planned",
          "title": "<non-empty>"
        }
      ],
      "state": "planned",
      "supersedes": [],
      "title": "<non-empty>",
      "work_item": "FEAT-<uuidv7>"
    }
  ]
}
```

文件使用 UTF-8、结尾换行、两空格缩进和字典序 key；未知字段、重复 key、符号链接、非普通文件、跨目录路径或非规范 UUIDv7 一律拒绝。

### 2.2 Schema 1 只读兼容

历史 `schema: 1` 台账继续接受 `PEND-*`、既有状态、里程碑、提交和可信审计，并可被查询或由 Review 完成既有活动项。任何新建或主动升级的 delivery-plan 必须使用 schema 2；不得批量改写历史 PEND，也不得把 PEND 换号成 FEAT。仓库出现首个 `Nova-Schema: 2` commit 后，新 schema 1 commit 直接拒绝。

### 2.3 聚合与蓝图投影

有效任务为 state 不属于 superseded、cancelled 的记录。工作项 completed 只能从可信 Review PASS 派生；内部里程碑 completed 只表示该阶段证据齐备，不能关闭任务。

| 输出 | 计算规则 |
|------|----------|
| `total` | 当前有效 FEAT 数 |
| `completed` | 有可信 Review PASS 的有效 FEAT 数 |
| `current` | state 为 active、review_pending 或 blocked 的任务；默认至多一个，并带内部里程碑进度 |
| `remaining` | 有效且非 completed、非 current 的任务，按依赖拓扑和登记顺序排列 |
| `blocked` | 当前任务或当前里程碑的具体阻塞原因；没有时为“无” |

蓝图投影全部未完成有效 FEAT，且只使用 `待澄清 / 待开发 / 待Review`：设计尚未确认时为待澄清；设计已确认且尚无完整实现结果时为待开发；required 实现提交完成后为待Review。active 不制造第四种文档状态。设计依据必须是具体待澄清说明或可点击设计锚点；依赖必须是无、稳定编号或带具体问题的待确认说明；需求引用必须是可校验 `REQ-...@vN` 链接。

`status=development` 要求 total > 0 且 completed < total；`status=implemented` 要求 completed = total、total > 0 且 current、remaining、blocked 均为空。台账、蓝图、需求索引和可信审计任一不一致时失败封闭。

## 3. 一致性与并发

| 场景 | 原子边界 | 并发结果 | 幂等规则 |
|------|----------|----------|----------|
| 创建初始台账 | 锁定 requirement checkpoint、schema 2 候选台账、蓝图投影和需求状态后一次 delivery-plan 提交 | 任一文件或 HEAD 漂移整次拒绝 | 相同基线、候选字节和幂等键返回既有 plan commit |
| 调整交付计划 | 重读上一有效 plan，验证历史保留、依赖、范围等价和新投影后一次提交 | 只允许基于最新 plan_version 的候选成功 | 相同上一版本与规范化候选不增加版本 |
| 激活任务或里程碑 | 同时验证依赖、current 总数、设计确认指纹、蓝图引用和里程碑状态 | 已有 current 或依赖变化时拒绝旧候选 | 重复激活同一对象不增加版本 |
| Review PASS 聚合 | 在关闭锁内校验实现 commit 与 Review 修正摘要，一次写入修正、审计、台账、蓝图和需求投影 | 字节、index 或 HEAD 漂移时整次失败，不产生部分提交 | 相同批次、实现集合和修正摘要返回既有结果 |
| 查询进度 | 从同一 commit 快照读取台账、蓝图与审计索引 | 读取中 HEAD 变化则重试一次，仍漂移时失败 | 相同 commit 与 Requirement-Ref 返回逐字等价结果 |

### 3.1 提交与计划变化

一个 FEAT 默认只有一个实现结果 commit。仅当台账预先存在两个以上具有独立恢复价值的内部里程碑，且前一提交已作为对应 completed 里程碑证据保存时，才允许沿用同一 FEAT 追加下一提交；按文件、技能、测试轮次或随手修改拆分一律拒绝。PATCH、FIX、MAINT 没有台账里程碑，Review 前只允许一个结果 commit；继续修正应在安全前提下 amend，而不是制造碎片提交。

新增、替代、重排、依赖调整、完成定义等价修订、激活、设计绑定、里程碑变化、提交 Review、完成、取消和阻塞变化都递增 plan_version 并追加匹配的受限 change。原任务保留为 superseded/cancelled；减少或无法证明等价的业务验收返回需求阶段升级版本。

### 3.2 Review 单提交闭环

REJECT 轮次只保存发现、工作树修正和复验结果，不创建 commit。最终 PASS 的 manifest 固定实现 commits、Review 修正完整 diff 的 SHA-256、审查范围、逐轮结论和有效测试证据；审计内容不嵌入尚不存在的 closure commit hash。校验器从 Git index 重算修正摘要和确定性审计输出，随后将修正、审计、蓝图、设计、台账和需求投影作为一个 `review(review): 中文结果摘要` commit 提交。这样审计可以由其 Git 归属反查 closure commit，又不存在自引用哈希循环。

## 4. 失败与恢复

| 失败点 | 对外结果 | 恢复或补偿 | 责任方 |
|--------|----------|------------|--------|
| requirement checkpoint 缺失、不是 ancestor、字段混合或摘要失配 | 拒绝创建或读取台账 | 恢复上一合法 checkpoint；重新校验并精确提交 | 需求治理与交付治理 |
| 无架构差量却创建 ARCH，或实际差量没有合法 ARCH | 拒绝下游激活，不伪造架构成果 | 删除未提交伪成果，或回到架构阶段确认真实差量 | 架构治理 |
| schema、FEAT 边界、里程碑、身份、依赖或完成定义非法 | 整份计划拒绝 | 修正候选并完整重验；不得只提交首个合法任务 | 开发交付 |
| 蓝图投影、需求链接或台账不一致 | delivery-plan 或 Review 闭环失败，上一投影保持有效 | 基于最新 commit 重建候选后原子重试 | 交付治理 |
| PATCH/FIX 语义证据不足，或工作项被碎片化提交 | 不接受分类或提交 | 回到当前任务补齐证据、合并结果，必要时返回需求或架构 | 开发与 Review |
| REJECT 轮次出现 commit，或 closure 修正摘要/审计不一致 | 不接受 Review PASS，不关闭任务 | 保留工作树修正，重建唯一最终闭环候选 | Review 治理 |
| 历史 PEND 被改号、重写或 schema 2 后新建 PEND | 校验与 Doctor FAIL | 恢复不可变历史；新工作重新分类为 FEAT/PATCH/FIX/MAINT | 交付治理 |
| 进度查询无法唯一定位需求或证据冲突 | 返回明确失败，不输出推测进度 | 要求精确 Requirement-Ref，修复持久化冲突后重查 | 交付治理 |
