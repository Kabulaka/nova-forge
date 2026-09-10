---
name: release-nova-forge
description: 分析 Nova Forge 尚未发布的变更，建议下一个 SemVer 版本，并在维护者确认后通过仓库的标签触发式 GitHub Actions 工作流准备和发布版本。只用于发布当前 Nova Forge 仓库；不用于其他项目，也不得把版本选择视为推送授权。
---

# 发布 Nova Forge

发布当前仓库时，不得绕过版本、Review、Git 或 GitHub 安全门禁。版本建议、本地发布准备、Review、远程发布和 GitHub 在线验收是相互独立的证据状态，必须分别报告。

## 1. 确认目标与当前状态

只有仓库根目录同时存在以下事实时才运行：

- `package.json` 的 `name` 为 `nova-forge`；
- `.github/workflows/release.yml` 使用 `v*.*.*` 标签触发；
- 存在 `scripts/sync-version.mjs` 和 `scripts/validate-release-notes.mjs`；
- 存在 `docs/release-notes/`。

提出版本建议前，检查当前真实状态：

- 当前分支、`HEAD`、工作树、暂存区、上游及领先/落后数量；
- 本地和远端稳定版本标签；带注释标签必须解析到实际 commit；
- GitHub 上已发布且非草稿、非预发布的 Release；
- `package.json.version` 以及全部 manifest、marketplace 版本；
- 从最近一个已发布稳定版本到当前 `HEAD` 的 commits 和完整 diff。

使用 `git ls-remote` 与 `gh release` 取得当前远端证据。不得根据本地文件或旧输出声称远端标签、Release、工作流结果或资产存在。工作树存在无关改动时，在发布准备前停止并保留这些改动。

## 2. 建议版本但不替维护者选择

以最近一个已发布的稳定 Release 作为变更日志基线；以现存稳定标签或 Release 中的最高版本作为版本下限，失败或未完成发布所占用的版本不得被静默复用。

存在稳定 Nova `Work-Item` 时按工作项聚合提交。一个实现 commit 及其 Review closure 只算一个逻辑变更，但两者都保留为证据。面向用户的 Highlights 不写纯审计记账内容；提交标题含义不明确时必须检查完整 diff 后再分类。

按尚未发布变更中的最高影响建议最小版本：

| 尚未发布的最高变化 | 当前主版本为 `0` | 当前主版本为 `1+` |
|---|---:|---:|
| 明确不兼容或破坏性行为 | 下一个次版本 | 下一个主版本 |
| 存在新的 `FEAT-*` 或等价向后兼容能力 | 下一个次版本 | 下一个次版本 |
| 只有 `FIX-*`、`PATCH-*`、维护、文档或 Review 修正 | 下一个修订版本 | 下一个修订版本 |
| 没有值得发布的变化 | 不发布 | 不发布 |

当前项目的固定示例：

- 最近版本为 `v0.1.0`，之后只有修复或维护：建议 `v0.1.1`；
- 最近版本为 `v0.1.0`，之后至少有一个新功能：建议 `v0.2.0`。

向维护者展示基线、按工作项聚合的证据、识别出的最高变化类别、建议版本及不确定项，然后只询问维护者选择哪个具体版本。取得选择前不得修改文件、提交、创建标签或推送。维护者选择的版本低于计算出的最低版本时，必须用具体不兼容变化说明冲突；不得静默接受版本冲突或降级。

## 3. 在本地准备选定版本

维护者选择版本后依次执行：

1. 重新检查 `HEAD`、工作树、上游、远端标签和 Release；选定标签已在任何位置存在或基线漂移时失败关闭。
2. 把 `package.json.version` 设置为不含 `v` 的选定版本，再运行 `node scripts/sync-version.mjs`，使两个插件 manifest 和两个 marketplace 保持一致。
3. 根据已验证且按工作项聚合的变化创建 `docs/release-notes/vX.Y.Z.md`。沿用既有 Release Notes 样式，至少包含 `Overview`、`Highlights`、`Installation`、`Requirements` 和 `Upgrade Notes`；只有证据支持时才增加 `Features` 与 `Fixes`。`Full Changelog` 的结束标签必须是选定版本，非首版从最近已发布稳定标签开始比较。
4. Release Notes 只描述用户可观察结果、固定到选定标签的安装命令、兼容或迁移影响、已知限制及已验证运行要求。不得只凭提交标题生成结论，不得遗留占位符。
5. 执行 `npm run check:release-notes` 和 `npm run check`；失败时修复后再继续。
6. 发布准备提交继续服从仓库 Nova 治理。版本 JSON 与 Release Notes 通常共同形成一个 `MAINT-*` 结果 commit，且不符合 `EX-DOC`；校验完整 staged diff 和提交消息。不得虚构豁免，也不得把测试称为 Review。

该 MAINT commit 要求 Review 时，如果用户尚未明确授权 Review，就在本地完成报告后停止。不得从尚未 Review 的 required commit 创建发布标签。

## 4. 取得精确发布授权

任何远端写入前，向维护者展示：

- 选定标签和目标完整 commit；
- `origin` 的准确 push URL 与目标分支；
- 本地和远端领先/落后状态；
- 本地验证结果和 required Review 结果；
- 即将执行的两个命令：`git push origin main` 与 `git push origin vX.Y.Z`。

必须取得覆盖上述具体推送的明确授权。选择版本、批准 Release Notes、批准本地 commit 或普通“继续”都不是 push 授权。发布过程中不得配置或替换远端仓库。

## 5. 通过标签工作流发布

取得精确授权且已验证状态未变化后依次执行：

1. 把通过 Review 的发布 commit 推送到 `origin/main`。
2. 验证 `origin/main` 已解析到预期 commit。
3. 在该精确 commit 上创建唯一的本地带注释标签 `vX.Y.Z`，消息为 `Nova Forge vX.Y.Z`。
4. 只把该标签推送到 `origin`。
5. 持续查看 `Release` GitHub Actions，直到得到终态结论。
6. 在线验证 GitHub Release 的标签、标题、正文及两个资产：`nova-forge-X.Y.Z.tgz` 与 `SHA256SUMS`。

正常路径由 Action 创建 GitHub Release，本技能不得同时运行 `gh release create`。

推送 `main` 失败时不得创建或推送标签。标签创建或推送失败时保留精确现场并报告。标签已经推送但 Actions 或 Release 创建失败时，不得删除、移动、强推或静默复用标签，也不得替换已经发布的资产；报告工作流 URL 和失败证据。重跑、修复版本或破坏性标签操作必须重新取得明确决定。

## 6. 完成报告

分别报告以下状态：

- 版本建议证据及维护者最终选择；
- Release Notes 路径及版本同步文件；
- 本地检查与 Nova Review 状态；
- 发布准备 commit；
- `main` 推送和标签推送结果；
- GitHub Actions 终态；
- GitHub Release URL 及已验证资产；
- 未执行或未验证事项。

只有远端标签、成功工作流、GitHub Release 和两个资产均已在线验证，才能宣称发布完成。
