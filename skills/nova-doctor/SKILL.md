---
name: nova-doctor
description: 只读检查当前项目的 Nova 文档、引用、审计与迁移状态。用于项目健康检查、诊断 Nova 校验失败或判断是否需要迁移；不用于检查全局技能安装、更新技能源码、修复数据或执行迁移。
---

# Nova Doctor

只诊断调用时所在的当前项目。不得接受或推断另一个项目路径，也不得检查 `~/.codex/skills`、技能源码仓库或远端版本。

## 执行

1. 从当前工作目录确定 Git 仓库根目录；无法确定时报告失败。
2. 使用本技能目录中的 `scripts/nova_doctor.py`，保持当前工作目录不变：

   ```bash
   python /absolute/path/to/skills/nova-doctor/scripts/nova_doctor.py
   ```

3. 原样保留每项 `PASS / WARN / FAIL` 结论。失败时引用脚本给出的证据和定向校验命令，不用推测替代诊断。

脚本只读检查 `.nova` 布局、迁移需求、蓝图、需求、架构、共享能力、交付台账、设计、Git 提交治理、审计和本地 Markdown 引用。缺少可选层可以通过；缺少核心蓝图、存在坏引用、Schema 不兼容或适用校验器失败必须报告 `FAIL`。

提交治理与现有校验器共同覆盖：schema 1 历史/schema 2 激活顺序；REQ/ARCH/FEAT/PATCH/FIX/MAINT 的身份和分类映射；schema 2 的中文首行及 scope 白名单；新 PEND 逃逸；蓝图九列表头、`待澄清 / 待开发 / 待Review`、具体设计/依赖表达和需求超链接；ARCH checkpoint 可信性；schema 2 delivery ledger 与 FEAT 投影；一个实现结果 commit 及已登记里程碑例外；Review 修正与审计/投影只形成一个 closure commit；历史 PEND 审计兼容。

Doctor 只验证可由字节、Git 历史、引用和状态映射确定的事实。工作项是否真正独立、PATCH/FIX 的业务证据是否充分、架构方案是否合理仍由相应流程确认，不得用脚本假装完成语义判断。

## 边界

- 不执行 Git 写操作、网络访问、安装、修复、迁移或数据格式化。
- 不把 `WARN` 表述为完全健康，也不因项目失败而修改文件。
- 用户另行要求修复或迁移时，把脚本证据交给对应开发流程；本技能本身仍保持只读。
