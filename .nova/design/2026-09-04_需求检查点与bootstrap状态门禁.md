# 需求检查点与 bootstrap 状态门禁设计

> 设计规范版本：5
> 设计状态：已确认
> 收敛确认：用户明确确认@sha256:f4d6d0ef54ec8e6a66b5c361308b7a2f1f936cd10a9e096a3454db482b9f643d
> 演进来源：无
> Requirement-Ref：REQ-01a06a50-2732-704d-97d0-7a98b205a4ea@v1
> 工作包：WP-01

<a id="shared-context"></a>
## 1. 共享约束

### 1.1 问题与成功结果

| 问题 | 成功结果 |
|------|----------|
| 已确认需求目前只能随后续开发提交，且既有 Review 关闭会把关联需求直接标为已实现 | 已确认需求可立即形成独立本地检查点；本需求 bootstrap 的首个开发切片关闭后仍保留完整后续范围并显示开发中 |

### 1.2 共享契约

| 契约 | 语义键 | 唯一规则 |
|------|--------|----------|
| S-01 | 上游/权威来源 | 本工作包继承 `REQ-01a06a50-2732-704d-97d0-7a98b205a4ea@v1` 与已就绪交付治理架构；实现不得改变其提交分型、bootstrap 范围或状态聚合语义。 |

<a id="work-package-map"></a>
## 2. 工作包地图

| 工作包 | 角色 | 状态 | 交付结果 | 前置依赖 | 设计章节 |
|--------|------|------|----------|----------|----------|
| WP-01 | 能力 | 待Review | 交付独立需求检查点、开发中索引状态和 bootstrap 多切片关闭门禁 | 无 | [需求检查点与 bootstrap 状态门禁](#wp-01-requirement-checkpoint-bootstrap-gate) |

<a id="wp-01-requirement-checkpoint-bootstrap-gate"></a>
## WP-01 需求检查点与 bootstrap 状态门禁

### 契约

| 契约 | 维度 | 语义键 | 唯一规则 |
|------|------|--------|----------|
| WP-01-C01 | 交付边界 | WP-01/范围 | 本期实现 requirement 检查点提交、需求索引“开发中”状态及当前需求的 bootstrap Review 关闭门禁；不实现正式 delivery-plan 台账、五项进度查询、自动 Review、push、SVN 或团队项目管理集成。 |
| WP-01-C02 | 参与者与权限 | WP-01/授权 | 只有用户明确确认整份需求且需求索引与需求块校验通过后，需求技能才可创建精确范围本地 requirement commit；该提交不进入人工 Review，远程写入仍须独立授权。 |
| WP-01-C03 | 触发与输入 | WP-01/输入 | 检查点输入必须是同一仓库当前已确认的 `REQ-...@vN`、索引行、需求块路径、需求块字节 SHA-256 和可隔离的 staged diff；bootstrap 关闭输入必须是当前工作项可信 Review PASS 及蓝图中同一 Requirement-Ref 的剩余有效 PEND。 |
| WP-01-C04 | 结果、状态与不变量 | WP-01/检查点身份 | requirement commit 必须携带 `Nova-Schema`、`Commit-Kind: requirement`、`Requirement-Ref`、`Requirement-Path`、`Requirement-SHA256` 和 `Validation`，且只包含该需求块、索引及其直接需要的总体业务段落；不得携带 Work-Item、设计或 Review trailers。 |
| WP-01-C05 | 结果、状态与不变量 | WP-01/索引状态 | 需求索引接受“待实现、开发中、已实现、已更新”；开发中时“已实现版本”和“实现依据”必须同时为“无”或同时指向上一完整实现，不能把当前未完成版本写成已实现。 |
| WP-01-C06 | 结果、状态与不变量 | WP-01/bootstrap关闭 | 仅 `REQ-01a06a50-2732-704d-97d0-7a98b205a4ea@v1` 可在正式台账落地前使用临时门禁；当前切片 PASS 后只把需求置为开发中并保留另外两个 PEND，不能写入当前版本的已实现版本或实现依据。 |
| WP-01-C07 | 结果、状态与不变量 | WP-01/Review隔离 | Review 候选发现只选择合法且要求 Review 的 PEND/FIX/MAINT；requirement commit 即使与当前 HEAD 相邻也必须被排除，既有 Work-Item 与审计提交兼容行为保持不变。 |
| WP-01-C08 | 失败与恢复 | WP-01/失败封闭 | 元数据混用、路径越界、内容指纹失配、需求未确认、索引非法、staged diff 夹带、Git 基线漂移或 bootstrap 证据冲突时拒绝动作，不创建部分提交、不改写需求状态，并保留进入动作前的工作树和暂存状态。 |
| WP-01-C09 | AI 决策边界 | WP-01/实现决定 | 可在既有 Python 标准库、需求校验器和 Review Git 解析入口内选择最小复用结构并补齐测试；若需要改变已确认 trailers、bootstrap 适用范围、索引状态语义、新增依赖或扩大到正式台账，必须再次确认。 |

### 验收

| 覆盖契约 | 场景 | 预期结果 |
|----------|------|----------|
| S-01、WP-01-C01、WP-01-C02、WP-01-C03、WP-01-C04 | 确认并校验一个新需求后立即停止，不进入架构或开发 | 形成只含允许文件的独立 requirement commit，可从 trailers、commit 和需求块字节恢复 Requirement-Ref、路径与 SHA-256。 |
| WP-01-C04、WP-01-C08 | 分别提交字段混用、错误路径、错误 SHA-256、未确认需求及夹带无关文件的候选 | 每个候选均失败且不产生 commit，原工作树和暂存区保持可恢复。 |
| WP-01-C05 | 校验待实现、开发中无历史实现、开发中保留上一实现、已实现和已更新的索引，并构造字段冲突反例 | 合法组合 PASS；当前版本伪装已实现、单边“无”和非法状态均 FAIL。 |
| WP-01-C07 | 在历史中混合 requirement、work-item 与 audit commit 后查询 Review 候选 | 只返回合法且 `Review-Policy: required` 的 Work-Item，检查点和 audit 均不返回。 |
| WP-01-C03、WP-01-C06、WP-01-C08 | 对当前 bootstrap 工作项记录可信 PASS，同时蓝图仍有另外两个同需求 PEND | 当前工作项关闭，需求变为开发中，已实现版本与依据仍为“无”，另外两个 PEND 保留；证据冲突时整个关闭失败。 |
| WP-01-C07、WP-01-C09 | 执行既有非 bootstrap 单工作项关闭及提交契约回归测试 | 既有合法 Work-Item、审计记录和终态需求更新行为保持兼容，且无新增第三方依赖。 |
