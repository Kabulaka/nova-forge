# Nova 审计与关闭契约

## 1. 分片布局

```text
docs/audit/
├── features/
│   └── YYYY.jsonl
├── reviews/
│   └── YYYY/MM/<batch-id>.yaml
└── index/
    └── <sha256(work-item) 前两位>/<work-item>.json
```

功能归档每行一个 JSON 对象，跨年份按 `work_item` 唯一；可信审计提交中的工作项索引同时是该编号不可逆归档终态的权威标记，蓝图删除活动行不释放编号。Review 每批一个 `.yaml` 文件，但内容固定为严格 JSON（JSON 是 YAML 1.2 子集），可含多个工作项。工作项索引只保存归档年份、Review 相对路径和批次，用于按编号定向读取并校验三者一致；不得建立持续追加的 Markdown 总账。

## 2. Review manifest

`record-pass` 接受 JSON manifest：

```json
{
  "schema": 1,
  "batch_id": "NR-20260827-01",
  "reviewed_at": "2026-08-27T11:30:00+08:00",
  "reviewer": "agent-id-or-name",
  "conclusion": "PASS",
  "review_round": 1,
  "review_content_sha256": "<完整 Review diff 内容标识，64 位小写十六进制>",
  "review_scope": ["main:path/to/file"],
  "repositories": {
    "main": ".",
    "codex": "/local/path/to/.codex"
  },
  "items": [
    {
      "work_item": "PEND-001",
      "change_class": "designed",
      "commits": [
        {"repository": "main", "commit": "<full commit hash>"},
        {"repository": "codex", "commit": "<full commit hash>"}
      ],
      "validation": "pytest tests/example.py (pass)",
      "design_ref": "docs/design/2026-08-27_example.md#wp-01-example",
      "blueprint": "PROJECT_BLUEPRINT.md",
      "design_file": "docs/design/2026-08-27_example.md",
      "package_ids": ["WP-01", "WP-02"]
    }
  ]
}
```

`repositories` 把审计用稳定别名映射到本机 Git 根目录；路径只用于本次验证，不写入审计。省略时使用 `{"main":"."}`，commit 也可写单仓库 hash 字符串。`review_round` 必须是 1～3；`review_content_sha256` 按仓库别名、完整 commit hash 和 binary diff 的确定性顺序计算；`review_scope` 必须与这些完整 diff 的 `alias:path` 集合精确一致。一个 `PEND-*` 对应同一设计中的多个已交付工作包时，设计文档必须提供“工作项关闭映射”，manifest 的 `package_ids` 必须按映射顺序一次列全并原子关闭，不信任调用方自报的子集或超集。没有映射时，只允许该设计恰有一个蓝图活动工作项、且 `Design-Ref` 所属工作包是设计内唯一 `待Review` 工作包。`FIX-*`/`MAINT-*` 省略 blueprint、design_file 和 package_ids，`design_ref` 为 `none`。Manifest 与 item 均拒绝未知或缺失字段，只接受 PASS；PASS WITH NOTES 必须先完成 Review-Defer 记录，再以已处置后的 PASS 证据关闭。

## 3. 关闭不变量

- 每个 commit 必须存在于声明的 Git 仓库且 trailers 与 manifest 的工作项、类别、设计引用一致；manifest 必须覆盖所列仓库中该工作项的全部 required commits，不得遗漏或混入 exempt commit；审计只保存仓库别名和完整 hash，不保存本机绝对路径；
- `designed` 的蓝图必须恰有一行对应编号；设计中仍含未完成工作包的映射项必须与蓝图里引用该设计的活动工作项完全一致，全部已完成的历史映射可保留但不要求继续出现在蓝图，且全部 `待Review` 工作包有唯一归属；manifest 的 `package_ids` 必须与对应映射完全一致，其中全部工作包各出现一次且为 `待Review`；
- 同批可以关闭多个互不冲突的工作项；同一蓝图/设计的所有修改先在内存合成再写入；
- 写入前从同一快照校验全部输入、commit trailers、已有索引及三类审计记录，任一错误零写入；Git diff 中 C 风格引号与八进制 UTF-8 路径必须先严格解码为真实路径，无效转义或非 UTF-8 字节失败关闭；审计提交校验须从父提交重新解析工作项关闭映射并推导权威 `package_ids`，不得信任 Review 记录自报的集合，再推导蓝图、设计、年度追加行、索引和 Review 记录的唯一预期字节及文件模式，并与 staged/commit 快照逐项精确比较，允许路径内的任何额外删除、改写或非规范重排均拒绝；替换前重新核对全部已验证快照；写入阶段使用仓库内路径、目录 FD、拒绝符号链接和条件替换，失败时先原子移走当前目标再判断是否为本轮内容，只有本轮内容才撤销，非本轮内容通过独立备份与 `RENAME_NOREPLACE` 恢复；若恢复前又有更晚写入占据目标，保留目标、被移走内容和独立备份中未知内容，通用清理不得删除，不得用“先检查后替换/删除”的窗口覆盖后置并发内容；完成提交点后的临时清理失败不得触发回滚或形成部分关闭；
- 同一 `batch_id` 与完全相同内容可重复调用并复用；同 ID 不同内容拒绝；
- 年度 JSONL 不允许同一 `work_item` 跨年重复归档；月度路径由 `reviewed_at` 决定；索引、功能行和 Review item 必须逐字段一致。
- `record-pass` 在 Git 元数据目录持有仓库级短时排他锁，并在替换前核对源文件快照；锁超时或文件被并发修改时失败，不污染工作树、不覆盖新内容。
- `record-pass` 完成后以 `Nova-Audit-Schema` 审计提交记录生成文件；校验器要求传入 diff 与真实 staged diff 完全一致，并从 Git index 读取 staged blob。该提交按工作项与提交契约校验，不使用 `Work-Item`，因此不递归形成新待审项。

## 4. 查询

按稳定编号查询时先定位提交该哈希分片索引的最新 `Nova-Audit-Schema` commit，再从该 commit blob 验证索引、年度功能行、Review、蓝图/设计关闭内容、审计 trailers、manifest 摘要和精确变更路径；至少重新验证 `main` 仓库被审 commits、trailers、范围与审计提交前的完整覆盖。同一查询中多个工作项指向同一审计 commit 时，该 commit 的完整快照只验证一次并按 commit hash 复用结果。未提交的 `record-pass` 输出可幂等重放，但不能从待审集合排除。指定年份/月时，当前 `HEAD` 的目标年度分片只读取一次；为验证每个可信审计提交的精确父子变换，可读取该 audit commit 的父/子年度 blob，但同一 audit commit 不重复验证；其他年份分片即使损坏也不得被扫描。待审发现新 commit 使用已有可信归档编号时必须失败，不能再次提交同一工作项给 Reviewer；明确来源 FIX 的 `Related-Work-Item` 必须解析为可信归档 PEND。其余待审集合等于 `Review-Policy: required` 且 trailers 完整合法的未覆盖 Nova commits，工作树中自洽伪造、字段不全或相互矛盾的记录不得把提交排除。裸 Review 还要与当前会话 ready ID 求交集。
