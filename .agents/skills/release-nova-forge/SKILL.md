---
name: release-nova-forge
description: 自动分析 Nova Forge 未发布变更、选择最低合理 SemVer、准备并校验版本；只在提交前确认一次，确认后提交、推送标签并验收 GitHub Release。仅用于当前 Nova Forge 仓库。
---

# 发布 Nova Forge

把发布作为一条连续维护流程执行。用户说“发布”或“发布版本”后，自动完成版本判断、本地准备和校验；不启动 Nova Review。只在创建发布提交前确认一次，确认后连续完成提交、推送、标签、Action 监控和在线验收。

如果用户在同一请求中已经明确要求“提交并发布”，视为这一次确认已经给出，不再重复提问。用户只要求准备、明确不提交或不发布时，服从其限定。

## 发布前检查

仅在仓库根目录同时满足以下条件时继续：

- `package.json.name` 为 `nova-forge`；
- `.github/workflows/release.yml` 由 `v*.*.*` 标签触发；
- 存在版本同步、Release Notes 校验脚本及 `docs/release-notes/`。

一次性核对当前分支、HEAD、工作树、暂存区、上游领先/落后、push URL、远端 `main`、本地与远端稳定标签、GitHub 正式 Release、所有版本文件，以及最近稳定 Release 到 HEAD 的提交与完整差异。远端事实必须来自本轮 `git ls-remote` 和 `gh release`。

存在无法与本次发布分离的既有改动、远端回退、标签冲突或未完成同版本 Release 时停止并报告，不擅自覆盖、重置、变基、移动或复用标签。

## 自动确定版本

以最新已发布且非草稿、非预发布的稳定 Release 为变更基线，根据完整差异中的最高影响选择最低合理版本：

| 最高影响 | 当前主版本为 `0` | 当前主版本为 `1+` |
|---|---:|---:|
| 不兼容行为 | 下一个次版本 | 下一个主版本 |
| 向后兼容的新能力 | 下一个次版本 | 下一个次版本 |
| 只有修复、维护或文档 | 下一个修订版本 | 下一个修订版本 |
| 没有值得发布的变化 | 不发布 | 不发布 |

用户未指定版本时直接采用计算结果，不单独询问。用户指定版本时使用该版本，但低于最低合理版本、已被标签或 Release 占用时停止并说明冲突。

## 本地准备与唯一确认

1. 重新确认 HEAD、远端 `main`、目标标签和 Release 未漂移。
2. 更新 `package.json` 与 lockfile，再运行 `node scripts/sync-version.mjs`，同步两个插件 manifest 和两个 marketplace。
3. 创建 `docs/release-notes/vX.Y.Z.md`，并更新 README 中固定版本的安装命令。Release Notes 至少包含 `Overview`、`Highlights`、`Installation`、`Requirements`、`Upgrade Notes` 和正确的 `Full Changelog`；只写完整差异支持的用户可观察结果、兼容影响、限制与要求。
4. 运行一次 `npm run check`。该命令已覆盖版本、插件、Release Notes、工作流、测试和打包检查，不重复单独运行其子命令。失败时修复并重跑；同一失败三次仍未解决则停止。
5. 展示目标版本、发布文件、检查结果、拟用 Conventional Commit、完整目标 commit 范围、push URL，以及将执行的 `git push origin main` 和 `git push origin vX.Y.Z`，只问一次“是否提交并发布 vX.Y.Z？”。

这一个确认同时授权：创建所展示的本地发布提交、推送该提交到所展示的 `origin/main`、创建并推送所展示的版本标签，以及由标签工作流发布。不得把确认扩展到远端重配、强推、删除或移动标签、手工替换资产等其他操作。

发布准备不要求也不自动调用 `nova-review`。只有用户另行明确要求 Review 时才执行，并且不把它变成发布前置条件。

## 确认后的连续发布

确认仍有效且状态未变化时连续执行：

1. 只暂存已展示的发布准备差异，运行 `git diff --cached --check`，确认没有夹带文件。
2. 创建一个 `chore(release): 发布 Nova Forge vX.Y.Z` 本地提交，并记录完整 commit。
3. 推送 `origin main`，随后验证远端 `main` 精确指向该 commit；失败时停止，不创建标签。
4. 在该 commit 创建带注释标签 `vX.Y.Z`，消息为 `Nova Forge vX.Y.Z`，再执行 `git push origin vX.Y.Z`。
5. 监控该标签触发的 `Release` GitHub Actions 至终态。
6. 在线验证 GitHub Release 的标签、标题、正文、`nova-forge-X.Y.Z.tgz` 和 `SHA256SUMS`，并下载资产验证校验和。

正常路径只允许标签 Action 创建 Release，不运行 `gh release create`。标签已推送但 Action 或资产失败时保留现场并报告工作流 URL；不得删除、移动、强推、复用标签或替换资产，任何修复发布都由用户重新决定。

## 完成报告

发布成功后简要报告：版本及选择依据、发布 commit、`main` 与标签推送、Action 终态、Release URL、两个资产及校验和结果。只有这些远端证据均已在线验证，才能称为发布完成；否则明确停在哪一步和未完成事项。
