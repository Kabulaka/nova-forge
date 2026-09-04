# Nova 工作项与提交契约

## 1. 身份与分类

工作项 ID 是一次交付生命周期的跨会话稳定身份，commit 只是该身份的证据。可信审计归档是不可逆终态：活动工作项的原范围开发、测试和 Review 修复沿用原 ID；归档后任何变化重新分类建项，旧 ID 永久封存：

| 类别 | ID | 客观边界 | 默认 Review |
|------|----|----------|-------------|
| `designed` | `PEND-<UUIDv7>` | 新增或改变能力、接口、状态、权限、持久化、依赖、跨模块契约；必须有蓝图和设计工作包 | required |
| `adhoc` | `FIX-<UUIDv7>` | 修复既有契约内的局部问题，不新增能力或改变公共契约；不进入蓝图 | required |
| `maintenance` | `MAINT-<UUIDv7>` | 不改变运行时或测试语义的维护变更 | required，命中客观白名单才可 exempt |

无法证明是 `adhoc` 或 `maintenance` 时使用 `designed`；分类矛盾时不提交，先修正元数据。

新工作项使用本地无状态命令生成小写规范 UUIDv7：

```bash
python3 skills/nova-review/scripts/nova_review.py new-id --class designed
```

`--class` 可取 `designed`、`adhoc`、`maintenance`，分别生成 `PEND-*`、`FIX-*`、`MAINT-*`。既有纯数字 ID 继续合法且不得改写，但不得因蓝图删除活动行而重新分配；Review、归档前原范围修复提交和后续证据必须逐字沿用原 ID。生成器不读取登记表，不依赖锁、计数器、工作树、分支或主机状态。

长期需求身份使用独立命令 `python3 skills/nova-review/scripts/nova_review.py new-requirement-id` 生成 `REQ-<UUIDv7>`；它不是工作项，不进入 commit trailers 或 Review 选择。

归档后发现既有契约缺陷时创建新 FIX；新增能力或改变公共契约时创建新 PEND 并以新设计的“演进来源”链接终态设计；纯维护创建新 MAINT。明确源于已归档 PEND 的新 FIX 必须增加单值 `Related-Work-Item: PEND-*`，且该值必须与新 FIX 不同并能通过可信审计索引验证；无关任务不得伪造关联。

## 2. 豁免白名单

只有 `maintenance` 可豁免：

- `EX-DOC`：完整 diff 的新旧两侧路径均为 `.md`、`.txt` 或 `.rst`，且没有运行时配置、脚本、依赖、测试/fixture、符号链接、Gitlink/submodule 或二进制文件；删除和重命名也同时检查源路径与目标路径；
- `EX-FORMAT`：提供完整 diff；不允许新增、删除、重命名、文件模式变化、符号链接或 Gitlink；每个文件的新旧路径必须相同，删除所有空白后旧内容与新内容逐文件完全相同。

代码注释、拼写、日志或“看起来很小”若无法由上述规则从完整 diff 客观证明，仍使用 `Review-Policy: required`。豁免规则不适用于 `designed` 或 `adhoc`。

## 3. Requirement 检查点 trailers

用户明确确认整份需求且需求索引、需求块校验通过后，必须立即形成独立本地 requirement commit：

```text
Nova-Schema: 1
Commit-Kind: requirement
Requirement-Ref: REQ-018f22e2-79b0-7abc-8123-456789abcdef@v1
Requirement-Path: .nova/requirements/REQ-018f22e2-79b0-7abc-8123-456789abcdef_example.md
Requirement-SHA256: <需求块 staged 字节的 64 位小写 SHA-256>
Validation: requirements index/block (pass)
```

- 精确 staged diff 必须只包含 `.nova/PRODUCT_REQUIREMENTS.md` 和 `Requirement-Path`，两者均为普通 `100644` 文件且不得重命名；
- `Requirement-Ref`、需求块元数据、索引版本、路径 Key 和内容 SHA-256 必须逐字一致；
- 同一 `Requirement-Ref` 只能有一个可信 requirement commit；
- 不得携带 `Work-Item`、`Change-Class`、`Design-Ref`、`Review-Policy`、`Exemption-Rule`、`Related-Work-Item` 或 `Review-State`；
- 提交前使用 `validate-message --repo <根目录> --message-file <消息> --diff-file <完整 staged diff>`；下游使用 `query-requirement --repo <根目录> --requirement-ref <REQ@vN>` 恢复并验证基线三元组；
- requirement commit 不进入 Review 候选，也不生成工作项完成审计。

## 4. Work-Item commit trailers

每个 PEND/FIX/MAINT commit 必须恰有一组：

```text
Nova-Schema: 1
Work-Item: PEND-018f22e2-79b0-7abc-8123-456789abcdef
Change-Class: designed
Design-Ref: .nova/design/2026-08-27_example.md#wp-01-example
Review-Policy: required
Exemption-Rule: none
Validation: pytest tests/example.py (pass)
```

规则：

- `Design-Ref` 对 `designed` 必须是 `.nova/design/*.md#<anchor>`，其余类别必须为 `none`；
- 迁移前不可变 commit 中的 `docs/design/*.md#<anchor>` 只作读取兼容，确定性映射到 `.nova/design/`；新提交不得继续使用旧路径；
- `Review-Policy` 只允许 `required` 或 `exempt`；
- required 时 `Exemption-Rule: none`；exempt 时只能为上节白名单；
- 只解析提交消息尾部连续且完整的 trailer block；正文中的示例字段不算 trailers；
- `Validation` 写最低验收的命令并以 `(pass)` 结尾，不写可变 Review 状态；
- `Related-Work-Item` 可省略且最多出现一次，只允许 `adhoc` FIX 指向可信审计已归档的 PEND；普通校验检查格式，仓库感知校验、待审选择和关闭校验检查归档真实性；
- 未归档工作项的原范围后续修改继续使用相同 ID 并产生新 commit；归档后不得新增同 ID commit，也不得为新工作项复用旧号或修改旧审计掩盖冲突。

## 5. Review 关闭审计提交

`record-pass` 在既有 PASS 后生成的关闭与审计文件不构成新工作项，不得伪造 `MAINT-*` 或递归进入 Review。该次本地提交使用独立且恰好一组的 trailers：

```text
Nova-Audit-Schema: 1
Review-Batch: NR-20260827-01
Manifest-SHA256: <64 位小写十六进制>
Validation: nova-review validate-audit-message (pass)
```

提交前必须先精确暂存本批关闭文件，再用 `validate-audit-message` 对 staged diff 校验。传入 diff 必须与仓库真实 staged diff 逐字节一致；记录内容从 Git index 读取，不信任可能已继续变化的工作树。Git 输出的 C-quoted 路径须严格还原成真实 UTF-8 路径后再比较。校验器从 `HEAD`（已提交审计时为父提交）重新解析关闭映射、推导权威 `package_ids` 并执行确定性关闭函数，不能以 Review 记录自报集合为权威；随后逐字节推导年度 JSONL 只追加本批记录、索引与 Review 原先不存在且内容规范、蓝图只删除目标行、设计只完成目标工作包的唯一输出，并保持既有文件模式、新文件固定为普通 `100644`；staged/commit 的路径、blob 与模式必须全部相等。批次、manifest 摘要、严格 Review 记录、年度功能记录、每项索引、蓝图/设计关闭内容和路径必须完全一致，`Validation` 必须以 `(pass)` 结尾，且不得包含标准 `Work-Item` trailers 或额外路径。审计提交只保存已取得的 Review 事实，不产生新的 Review 授权或结论。

## 6. 提交权限

全局治理代表用户对每个任务在最低验收通过且无阻断后创建精确范围本地 Git commit 的持续授权，无需逐次询问；用户明确要求不提交时只撤回当次授权。不得提交未通过最低验收的代码。Git push、远程配置和 SVN commit 不由本契约授权，必须取得用户对具体操作的独立授权。
