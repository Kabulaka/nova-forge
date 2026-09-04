# Nova 身份与提交契约

## 1. 身份、分类与拆分

需求、架构和交付工作项使用不同身份：

| 对象 | ID | 客观边界 | 是否进入交付工作项表 |
|------|----|----------|----------------------|
| 需求版本 | `REQ-<UUIDv7>@vN` | 用户确认的业务契约版本 | 否 |
| 架构检查点 | `ARCH-<UUIDv7>` | 共享工程骨架、数据所有权、公共 API、事件或 Mock 的真实差量；零差量不创建 | 否 |
| 新能力 | `FEAT-<UUIDv7>` / `feature` | 一个独立、内聚、可暂停、可取消且有完整验收的交付结果 | 是 |
| 主动局部调整 | `PATCH-<UUIDv7>` / `patch` | 既有能力内的主动小改，不是缺陷，不新增业务能力或公共契约 | 否 |
| 缺陷恢复 | `FIX-<UUIDv7>` / `fix` | 有既有需求、设计、协议、测试或运行证据证明实际行为偏离预期 | 否 |
| 维护 | `MAINT-<UUIDv7>` / `maintenance` | 不新增产品能力的依赖、构建、工具或文档维护 | 否 |

FEAT 只能沿稳定能力边界拆分。需求、架构、编码、测试等流程阶段，以及文件、模块、技能、代理或提交批次都不能成为拆项依据。多个步骤只有共同完成才有价值，或共同修改同一规模可控能力时，使用一个 FEAT 和内部里程碑。无法证明 PATCH/FIX/MAINT 边界时停止分类；新增业务语义返回需求，改变共享边界返回架构。

新 ID 使用无状态命令：

```bash
python3 skills/nova-review/scripts/nova_review.py new-requirement-id
python3 skills/nova-review/scripts/nova_review.py new-architecture-id
python3 skills/nova-review/scripts/nova_review.py new-id --class feature
python3 skills/nova-review/scripts/nova_review.py new-id --class patch
python3 skills/nova-review/scripts/nova_review.py new-id --class fix
python3 skills/nova-review/scripts/nova_review.py new-id --class maintenance
```

历史 `PEND-*`、schema 1 的 `designed / adhoc / maintenance`、引用和可信审计保持原样且可继续完成；任何新入口都不得再生成 PEND。可信审计归档后编号永久封存。明确源于已归档 FEAT 或历史 PEND 的新 FIX 增加单值 `Related-Work-Item`，并由仓库感知校验验证来源。

## 2. 首行与 scope

所有 schema 2 提交首行必须为：

```text
type(scope): 中文结果摘要
```

- type 表示性质：requirement=`req`、architecture=`arch`、delivery-plan=`plan`、feature=`feat`、patch=`patch`、fix=`fix`、maintenance=`maint`、Review closure=`review`；
- scope 表示整个原子提交主要属于哪个稳定能力域，只能取 `requirements / architecture / delivery / review / doctor / plugin / discovery / release`；
- 选择覆盖整个提交的最小共同归属；Work-Item、状态、文件名及 `all / misc / core / governance` 不能作为 scope；
- 摘要必须含中文结果表达，不以句号结尾。Conventional Commits 不限制自然语言，中文 UTF-8 摘要合法。

示例：

```text
feat(delivery): 增加交付任务状态投影
fix(review): 修复归档任务重复选择
patch(discovery): 调整技能发现提示
maint(release): 更新发布校验依赖
```

## 3. Schema 生命周期

新协议使用 `Nova-Schema: 2`。不可变 schema 1 commit 继续按旧字段和语义只读验证；仓库一旦出现首个合法 schema 2 commit，之后再创建 schema 1 commit 必须失败。提交尾部只解析连续 trailer block，不得写可变 `Review-State`，也不得混合 checkpoint、work-item 和 Review closure 字段。

## 4. Requirement checkpoint

```text
req(requirements): 确认订单退款需求

Nova-Schema: 2
Commit-Kind: requirement
Requirement-Ref: REQ-018f22e2-79b0-7abc-8123-456789abcdef@v1
Requirement-Path: .nova/requirements/REQ-018f22e2-79b0-7abc-8123-456789abcdef_example.md
Requirement-SHA256: <64-lower-hex>
Validation: requirements index/block (pass)
```

精确 diff 只含总体需求索引和该需求块，均为普通 `100644` 且不重命名；引用、元数据、版本、路径 Key 和 staged 内容摘要逐字一致。同一 Requirement-Ref 只有一个可信 checkpoint。它不进入 Review 或工作项审计。

## 5. Architecture checkpoint

只有真实共享架构差量才创建：

```text
arch(architecture): 固化订单事件契约

Nova-Schema: 2
Commit-Kind: architecture
Architecture-Ref: ARCH-018f22e2-79b0-7abc-8123-456789abcdef
Requirement-Ref: REQ-018f22e2-79b0-7abc-8123-456789abcdef@v1
Validation: architecture contracts (pass)
```

提交至少包含一个 `.nova/architecture/` 契约路径，只含本次共享差量及其直接确定性校验更新，不重命名；Requirement-Ref 必须有可信需求 checkpoint，Architecture-Ref 全仓唯一。无差量时不得创建编号、修改文件、提交或 Review。ARCH 不携带 Work-Item trailers，也不进入交付工作项表。

## 6. Delivery-plan checkpoint

```text
plan(delivery): 建立退款需求交付计划

Nova-Schema: 2
Commit-Kind: delivery-plan
Requirement-Ref: REQ-018f22e2-79b0-7abc-8123-456789abcdef@v1
Requirement-Commit: <trusted-requirement-commit>
Requirement-SHA256: <64-lower-hex>
Plan-Version: 1
Validation: nova-delivery validate (pass)
```

精确 diff 必含 schema 2 台账，只可额外包含蓝图投影、需求状态行和该台账逐字绑定的设计文件；无关设计不得夹带。初始版本一次性列出全部独立 FEAT、内部里程碑、依赖、完成定义和 Requirement-Ref；蓝图只投影未完成 FEAT。Requirement-Ref + Plan-Version 全仓唯一，不进入 Review。

## 7. Work-Item commit

```text
feat(delivery): 增加交付状态校验

Nova-Schema: 2
Work-Item: FEAT-018f22e2-79b0-7abc-8123-456789abcdef
Change-Class: feature
Design-Ref: .nova/design/2026-09-04_example.md#wp-01-example
Review-Policy: required
Exemption-Rule: none
Validation: python3 tests/example.py (pass)
```

映射固定：

- feature → FEAT，必须有 `.nova/design/*.md#anchor`，必须 Review；
- patch → PATCH，`Design-Ref: none`，必须 Review；
- fix → FIX，`Design-Ref: none`，必须 Review；
- maintenance → MAINT，`Design-Ref: none`，默认 Review。

一个工作项默认形成一个完整实现结果 commit。FEAT 只有在台账预先登记多个具有独立恢复价值的内部里程碑，且上一提交已绑定已完成里程碑时，才可追加同编号提交；PATCH/FIX/MAINT 在 Review 前只允许一个结果 commit。普通继续修改优先在安全边界内 amend，不按文件或修复轮次制造碎片。

## 8. 维护豁免

只有 maintenance 可豁免：

- `EX-DOC`：完整 diff 的新旧两侧都只是非运行时 `.md/.txt/.rst`，不含脚本、配置、依赖、测试、fixture、符号链接、Gitlink 或二进制；
- `EX-FORMAT`：无新增、删除、重命名、模式或二进制变化，逐文件删除所有空白后内容完全相同。

命中时使用 `Review-Policy: exempt` 和对应 Exemption-Rule；其他情况 required + none。代码注释、日志、拼写或“改动很小”不能主观豁免。

## 9. Review 单提交闭环

实现 commit 后才可进入 Review。REJECT 轮次记录发现、修正和复验，但不提交。最终 PASS 的 manifest 必须覆盖目标工作项全部实现 commits、完整 Review 修正 diff 的 SHA-256、审查范围、逐轮问题与有效测试证据。随后只创建一个闭环提交：

```text
review(review): 完成交付状态校验审查

Nova-Audit-Schema: 2
Review-Batch: NR-20260904-01
Manifest-SHA256: <64-lower-hex>
Review-Fix-SHA256: <64-lower-hex-or-none>
Validation: nova-review validate-audit-message (pass)
```

该提交同时包含全部 Review 修正、确定性审计、蓝图/设计关闭和台账/需求聚合更新。审计保存实现 commits 与 Review 修正摘要，不把尚不存在的 closure commit hash 写入自身内容；提交后通过审计文件的 Git 归属反查 closure commit，因此没有哈希自引用。staged diff、manifest、审查范围或 HEAD 任一漂移时整次失败，不产生部分关闭。schema 1 的既有独立 audit commit 保持兼容。

## 10. 提交权限

最低验收通过且无阻断后，允许创建精确范围本地 Git commit；用户当次明确“不提交”则停止。Git push、远程配置和 SVN commit 始终需要对具体操作的独立授权。
