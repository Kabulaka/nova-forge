# Nova 会话检查点数据契约

> 数据契约版本：2
> Contract-Key：DATA-SESSION-CHECKPOINT-01
> 所有者：状态核心

## 1. 所有权

| 数据对象 | 权威写入方 | 允许读取方 | 禁止行为 |
|----------|------------|------------|----------|
| 静态治理规则 | `codex/AGENTS.global.md` 及插件版本 | 双宿主 `SessionStart` 适配器 | 把会话状态回写到静态规则或每轮注入全文 |
| 结构化权威状态 | 当前会话中的 AI 经绑定可信会话作用域的最小 MCP 工具提交 | 同宿主同会话 Hook、MCP 查询与恢复流程 | 从 transcript、压缩摘要或未经标记的自然语言自动推断正式决定，或由模型指定其他 host/sessionId |
| 检查点文件 | `runtime/core/` 原子存储器；位于稳定 Nova 用户私有根的宿主分区，只是上述会话内权威状态的持久化投影，不是第二套权威 | 当前宿主适配器与状态核心 | 依赖插件版本缓存、独立改写权威语义，或在宿主间、会话间、设备间、团队间读取继承 |
| 恢复胶囊 | 状态核心从最近有效检查点确定性生成 | 当前会话 `SessionStart` | 把候选决定、暂存范围或不可信字段提升为已确认状态 |

## 2. 数据约束

| 字段或关系 | 类型或范围 | 不变量 | 兼容规则 |
|------------|------------|--------|----------|
| schemaVersion | 正整数 | 由状态核心显式校验，未知主版本拒绝读取 | 只允许有确定性迁移器的旧版本升级 |
| pluginVersion | SemVer | 记录写入方版本，不替代 schema 兼容判断 | 插件升级后仍须通过 schema 兼容校验 |
| scopeBinding | 宿主适配器从 Hook 公共输入建立的只读当前 host、sessionId 摘要和随机能力 | MCP 进程实例只服务该绑定，写入/查询参数不接受 host 或 sessionId；缺失、错配、重放能力一律拒绝 | 新会话必须建立新能力；能力不落入检查点、日志或模型上下文 |
| host、sessionId | `codex` 或 `claude-code`；可信绑定中宿主原始会话 ID 的不可逆摘要 | 二者共同构成隔离键，原始会话 ID 不进入文件名 | 不允许跨 host 或 sessionId 回退查找 |
| eventWatermark、coveredEventWatermark、dirty | 宿主事件单调水位、检查点覆盖水位、布尔值 | `UserPromptSubmit` 与除本插件 MCP 外的 `PostToolUse` 只递增事件水位并置 dirty；检查点持久化成功且覆盖当前水位后才清除 dirty | 漏写、旧水位或未来水位检查点均不得成为 Stop 后或压缩后的恢复 authority；宿主回答与原生压缩仍须放行 |
| authorityGeneration | 单调递增正整数 | 只在权威 taskCapsule 改变时递增；同一隔离键只有更高 authority generation 可替换权威状态 | 重复提交相同幂等键、payload 和覆盖水位返回既有代 |
| leaseVersion、lastActivityAt、expiresAt | 独立单调租约版本和 UTC 时间戳 | 可信 `SessionStart` 或成功检查点写入刷新租约；普通 MCP 查询不刷新；`lastActivityAt=max(旧值, 当前时钟)`，`expiresAt=lastActivityAt+30天` | 同 authority generation 只允许更高 leaseVersion 原子替换；时钟回拨不得缩短保留期 |
| authorityState | `user-confirmed`、`delegated-ai-candidate`、`verified-evidence`、`explicitly-excluded`、`pending` | 每项状态保留来源类别，候选与 pending 不得作为确认项注入 | 新类别需要 schema 升级和正反用例 |
| taskCapsule | 目标、阶段、确认决定、排除、委托范围、当前问题、未决差量、`stageProjection`、活动交付范围、证据、文件与提交状态、下一动作 | 必填集合通过 schema 校验；`stageProjection` 必须按下表从同一权威快照生成，空数组与未知不能互相替代 | 缺失必填字段或无法无损重建完整 `stageProjection` 使整代无效，不用默认值猜测 |
| controlDocuments | 绝对路径、SHA-256、加载状态 | 不保存正文；路径与指纹共同决定是否复用已有理解 | 指纹变化时只标记需精确重载受影响文档 |
| compactionHandshake | attemptId、frozenGeneration、frozenWatermark、completedGeneration、injectedGeneration | 有覆盖检查点时由 `PreCompact` 冻结、`PostCompact` 完成、`SessionStart(compact)` 注入并记录；三者必须同作用域且 generation/watermark 相等 | 重复同事件幂等；错序、缺失或冲突事件停止 Nova authority 续接并降级为无权威上下文，但不停止宿主原生续接 |
| resourceLimits | JSON-RPC frame 320 KiB；规范化 checkpoint payload 256 KiB；字符串 8 KiB；每数组 128 项；嵌套深度 4；每宿主 512 MiB/2000 会话，全局 1 GiB | frame 超限在完整读取/JSON 解析前终止；字段和 payload 超限在规范化、哈希、临时文件前拒绝；当前代与备份均计入配额 | 先清理过期且未加锁作用域；未过期状态不逐出，仍不足则拒绝新写入或新会话 |
| checksum | 覆盖规范化 authority、租约及握手 envelope 的 SHA-256 | 写入完成前计算，读取不一致则拒绝该 envelope | 算法变化需要 schema 升级 |
| secretScan | 禁止字段名、令牌形态和调用方显式敏感标记 | 命中即拒绝整次写入且不产生新代 | 规则更新不追溯解密或上传历史状态 |
| stateRoot | 默认用户主目录下 `.nova`，或规范化绝对 `NOVA_HOME`；目录权限和真实可写探针必须通过 | 状态、rendezvous、迁移记录和临时文件均不得逃出规范化根；不得以项目目录、系统临时目录或插件缓存静默替代 | 根位置改变必须通过显式覆盖或确定性迁移，不得按可写性猜测多个候选根 |
| hostPartition | `codex`、`claude-code` 两个物理分区 | 状态路径和 rendezvous 路径均先按 host 分区，`scopeKey` 再绑定 host 与 sessionId；另一宿主分区不可枚举回退 | 新宿主值需要 schema 与路径迁移并补齐隔离矩阵 |
| migrationRecord | 源宿主、源根指纹、目标根指纹、迁移版本、已验证作用域集合、状态和校验和 | 单宿主迁移记录原子提交后目标根才成为唯一权威；不得包含原始会话 ID、能力或秘密，不得删除源状态 | 中断可从最后已提交记录幂等继续；未知迁移版本或记录校验失败时停止切换 |

### 2.1 `stageProjection` 持久化映射

| 投影字段 | 权威状态来源 | 持久化与恢复不变量 |
|----------|--------------|--------------------|
| inheritedContracts | 进入当前阶段前已存在的 `user-confirmed` 正式契约引用、真实来源阶段与证据位置；需求阶段允许同一需求权威内的既有总体范围和需求版本，架构与开发阶段只允许上游正式契约 | 只保存引用和真实来源标记；恢复后不得复制为本阶段决定、把同阶段来源伪装为上游阶段或改写确认状态 |
| stageEvidence | 当前阶段 `verified-evidence` 项及其 evidenceLocator | 证据位置逐项保留；证据漂移只能触发重新验证，不得改写成无来源事实 |
| stageDecisions | 当前阶段 `delegated-ai-candidate` 项所引用的 disclosedDecision 及直接依赖 | 只保存已完整披露的 AI 候选；用户确认项、继承契约和 pending 不得进入本集合 |
| unresolvedDeltas | 当前阶段 `pending` 项和与实际条目一致的显式数量 | 零值也必须保存；恢复不得把未知、暂存或相邻事项提升为当前差量 |
| resolutionBasis | 消解本阶段差量的 `user-confirmed`、`verified-evidence`、委托或 `explicitly-excluded` 项引用 | 差量为零时仍必填；持久化、备份、迁移和恢复均不得丢失或替换为无来源默认结论 |

`taskCapsule` 根级确认决定、排除和委托范围继续保存其原始 `authorityState`；上述映射只重建分组，不产生新事实、决定或确认。恢复流程必须从同一检查点快照重建完整 `stageProjection`，并逐项保持继承契约、阶段事实、AI 候选、用户确认和未决差量的类别边界。

## 3. 一致性与并发

| 场景 | 原子边界 | 并发结果 | 幂等规则 |
|------|----------|----------|----------|
| 写入检查点 | 持有作用域锁，重读水位与租约，在同目录创建临时文件、完整写入并同步后原子替换 envelope | authorityGeneration 提升优先；同代租约刷新必须合并已提交权威状态，旧水位写入拒绝 | 相同隔离键、幂等键、payload 和覆盖水位返回同一结果 |
| 保留最后有效状态 | 当前代替换前把已校验当前文件维护为单个备份 | 当前代损坏时只回退到校验通过且未过期的备份 | 重复恢复不创建新代 |
| 恢复阶段投影 | 校验同一 envelope 中的 `taskCapsule`、authorityState 与五字段映射后一次性重建 | 任一字段、来源或 `resolutionBasis` 缺失即拒绝整代；不得从 transcript、摘要或相邻类别补齐 | 同一 authorityGeneration 重复恢复得到逐项等价的 `stageProjection` |
| Hook、MCP 与租约并发 | 状态核心按可信作用域串行化 envelope 变更 | authority 写入重读并合并更高 leaseVersion；租约刷新不得覆盖更高 authorityGeneration | 同一事件 ID 或租约活动 ID 重复送达只记录一次 |
| 清理过期状态 | 先选 `expiresAt` 已过期作用域，再取得同一作用域锁并重读 leaseVersion 后删除 | 跳过正在写入、锁定或已刷新活动时间的键；时钟回拨不使未过期项提前删除 | 重复清理结果相同；只按最旧过期时间释放配额 |
| 旧根迁移 | 按宿主锁定迁移记录，逐作用域验证旧 envelope 后复制到目标宿主分区，完整同步目标并原子推进记录 | 同一宿主同一时刻只有一个迁移者；目标已有等价状态视为幂等，存在不同有效状态则停止并报告冲突 | 失败或进程中断不删除源状态、不发布未完成目标；重启从最后已提交迁移记录继续 |

## 4. 失败与恢复

| 失败点 | 对外结果 | 恢复或补偿 | 责任方 |
|--------|----------|------------|--------|
| Node.js 22.5+ 不可用 | 插件明确报告运行时缺失，自动检查点与恢复不生效 | 用户自行安装受支持运行时后重新启用；插件不安装 Node.js 或 Bun | 宿主适配器 |
| 状态根为空、相对、越界或无法真实写入 | Hook 报告降级并放行宿主，MCP 明确拒绝状态操作；二者均报告规范化目标路径和 `NOVA_HOME` 恢复方向，不宣称动态能力生效 | 修正绝对覆盖或目录权限后重试；不得静默切换项目目录、临时目录或插件缓存 | 状态核心 bootstrap |
| 旧根迁移损坏、中断或目标冲突 | 当前宿主迁移不提交权威切换，目标未完成内容不可读，原根保持完整 | 修复冲突后幂等重试；只复制通过 schema、校验和、宿主及会话作用域验证的状态 | 状态核心迁移器 |
| 作用域绑定缺失、错配或能力重放 | MCP 在读取任何其他会话状态前拒绝调用并记录无敏感值诊断 | 由当前宿主 `SessionStart` 重建新能力；不得接受模型提供的替代键 | 宿主适配器与 MCP |
| 边界漏写、旧水位或 dirty 未清除 | `Stop` 报告降级并放行回答；`PreCompact` 不冻结 Nova authority、报告降级并放行宿主原生压缩 | AI 可在后续可用时以当前可信水位重新提交完整结构化 taskCapsule；不得依赖阻断自救，不得复用旧代冒充最新 | 宿主适配器 |
| frame、字段、payload、会话数或磁盘配额超限 | 在对应分配阶段前确定性拒绝且不创建临时文件 | 只清理过期未锁定作用域；仍不足时保持旧有效代并要求缩减当前 payload 或释放明确范围 | MCP 与状态核心 |
| 写入、同步、替换、租约或秘密扫描失败 | MCP 写入失败且 Hook 可观察；不清除 dirty、不推进 current 指针；Hook 不阻断宿主回答或原生压缩 | 保留最近有效 envelope；没有覆盖当前水位的有效代时不建立或注入 Nova compaction authority，只使用无权威恢复上下文 | 状态核心 |
| 当前代损坏 | 拒绝当前代并记录校验失败 | 仅在备份同宿主、同会话、未过期且校验通过时恢复 | 状态核心 |
| 检查点缺失、过期、schema 不兼容或 `stageProjection` 不可完整重建 | 不注入权威状态，不宣称安全恢复 | 从当前会话与工作区事实定向恢复；仍缺失时只询问具体差量，禁止以默认值补齐五字段或提升 authorityState | 恢复流程 |
| `SessionStart` 注入超限 | 不截断单个权威字段后伪装完整 | 按固定优先级生成有界胶囊并显式列出未注入字段定位，必要时阻止推进 | 状态核心 |
| 压缩握手错序、缺失或 generation/watermark 不一致 | 显式报告 Nova 连续性核验失败，不写 `injectedGeneration`，但放行宿主续接 | 停止把 Nova checkpoint 续接视为权威，只注入静态规则和降级上下文；后续可从当前可见事实创建新检查点 | 宿主适配器 |
