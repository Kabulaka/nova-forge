# Nova 工作项与提交契约

## 1. 身份与分类

工作项 ID 是跨会话稳定身份，commit 只是该身份的证据：

| 类别 | ID | 客观边界 | 默认 Review |
|------|----|----------|-------------|
| `designed` | `PEND-<数字>` | 新增或改变能力、接口、状态、权限、持久化、依赖、跨模块契约；必须有蓝图和设计工作包 | required |
| `adhoc` | `FIX-<数字>` | 修复既有契约内的局部问题，不新增能力或改变公共契约；不进入蓝图 | required |
| `maintenance` | `MAINT-<数字>` | 不改变运行时或测试语义的维护变更 | required，命中客观白名单才可 exempt |

无法证明是 `adhoc` 或 `maintenance` 时使用 `designed`；分类矛盾时不提交，先修正元数据。

## 2. 豁免白名单

只有 `maintenance` 可豁免：

- `EX-DOC`：完整 diff 的新旧两侧路径均为 `.md`、`.txt` 或 `.rst`，且没有运行时配置、脚本、依赖、测试/fixture、符号链接、Gitlink/submodule 或二进制文件；删除和重命名也同时检查源路径与目标路径；
- `EX-FORMAT`：提供完整 diff；不允许新增、删除、重命名、文件模式变化、符号链接或 Gitlink；每个文件的新旧路径必须相同，删除所有空白后旧内容与新内容逐文件完全相同。

代码注释、拼写、日志或“看起来很小”若无法由上述规则从完整 diff 客观证明，仍使用 `Review-Policy: required`。豁免规则不适用于 `designed` 或 `adhoc`。

## 3. Commit trailers

每个 Nova commit 必须恰有一组：

```text
Nova-Schema: 1
Work-Item: PEND-001
Change-Class: designed
Design-Ref: docs/design/2026-08-27_example.md#wp-01-example
Review-Policy: required
Exemption-Rule: none
Validation: pytest tests/example.py (pass)
```

规则：

- `Design-Ref` 对 `designed` 必须是 `docs/design/*.md#<anchor>`，其余类别必须为 `none`；
- `Review-Policy` 只允许 `required` 或 `exempt`；
- required 时 `Exemption-Rule: none`；exempt 时只能为上节白名单；
- 只解析提交消息尾部连续且完整的 trailer block；正文中的示例字段不算 trailers；
- `Validation` 写最低验收的命令并以 `(pass)` 结尾，不写可变 Review 状态；
- 同一工作项后续修改继续使用相同 ID，并产生新 commit；不得为同一功能换号躲避历史。

## 4. Review 关闭审计提交

`record-pass` 在既有 PASS 后生成的关闭与审计文件不构成新工作项，不得伪造 `MAINT-*` 或递归进入 Review。该次本地提交使用独立且恰好一组的 trailers：

```text
Nova-Audit-Schema: 1
Review-Batch: NR-20260827-01
Manifest-SHA256: <64 位小写十六进制>
Validation: nova-review validate-audit-message (pass)
```

提交前必须先精确暂存本批关闭文件，再用 `validate-audit-message` 对 staged diff 校验。传入 diff 必须与仓库真实 staged diff 逐字节一致；记录内容从 Git index 读取，不信任可能已继续变化的工作树。Git 输出的 C-quoted 路径须严格还原成真实 UTF-8 路径后再比较。校验器从 `HEAD`（已提交审计时为父提交）重新解析关闭映射、推导权威 `package_ids` 并执行确定性关闭函数，不能以 Review 记录自报集合为权威；随后逐字节推导年度 JSONL 只追加本批记录、索引与 Review 原先不存在且内容规范、蓝图只删除目标行、设计只完成目标工作包的唯一输出，并保持既有文件模式、新文件固定为普通 `100644`；staged/commit 的路径、blob 与模式必须全部相等。批次、manifest 摘要、严格 Review 记录、年度功能记录、每项索引、蓝图/设计关闭内容和路径必须完全一致，`Validation` 必须以 `(pass)` 结尾，且不得包含标准 `Work-Item` trailers 或额外路径。审计提交只保存已取得的 Review 事实，不产生新的 Review 授权或结论。

## 5. 提交权限

全局治理代表用户对每个任务在最低验收通过且无阻断后创建精确范围本地 Git commit 的持续授权，无需逐次询问；用户明确要求不提交时只撤回当次授权。不得提交未通过最低验收的代码。Git push、远程配置和 SVN commit 不由本契约授权，必须取得用户对具体操作的独立授权。
