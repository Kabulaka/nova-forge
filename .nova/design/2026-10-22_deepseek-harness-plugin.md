# DeepSeek Harness 原生插件适配设计

> 演进来源：无。
> 项目依据：[项目蓝图](../PROJECT_BLUEPRINT.md)第 2—5 章、第六章“双宿主插件边界”及其[精确入口](../architecture/foundation/dual-host-plugin.md)。

<a id="design-summary"></a>
## 1. 目标与成功结果

| 问题 | 成功结果 |
|------|----------|
| 当前 Nova Forge 只提供 Codex、Claude Code 原生插件入口 | 用户通过 DSH 原生插件命令安装 Nova 后，指定 profile 自动获得五个技能及全局规则注入 |
| 直接复制技能不能覆盖完整插件体验 | 技能、SessionStart hook 随插件挂载、禁用及卸载，不要求修改用户级或项目级 AGENTS.md |
| 新宿主适配可能改变现有双宿主行为 | Codex、Claude Code 的原有安装、技能加载和规则注入通过回归，三端使用同一套 SOP |

本文定义待开发行为，不表示 DSH 适配已经实现或通过运行验收。官方参考基线为 `dsh-v0.2.1-rc.2`，固定提交 `687f282e8625c6b8d11ff58211a90524be2e4317`；研究日期为 2026-10-22。已取得官方文档、源码及测试用例的静态证据，尚未安装、运行 Harness 或执行其测试。

## 2. 范围

- 包含：DSH 原生 bundle 元数据、可直接运行的插件入口、包内技能注册、现有 hook 的官方兼容桥挂载、宿主交互适配、完整打包、安装说明及三端验证。
- 明确不包含：新增或删除技能、改变五个技能职责、复制一套 DSH 专用 SOP、写入用户 AGENTS.md、把技能复制到用户全局目录、接管宿主会话管理、建立新的持久状态或服务。
- 本次分发目标为现有 Git 仓库的版本化原生安装；新增 npm 发布渠道、DSH 市场索引及远程发布不属于本次交付。
- 当前蓝图描述的是既有双宿主骨架。实施前需由 Architecture 将支持宿主、DSH 插件入口和宿主专用依赖边界的最小差量同步至蓝图第一至第五章，再由 Development 实现；本次仅保存设计并登记待开发工作，不改写现有骨架或把计划能力登记为已实现能力。

## 3. 行为与契约

以下各行是对应行为的唯一规则；流程和验收只引用、验证这些规则。

| 契约 | 维度 | 唯一规则 |
|------|------|----------|
| 原生安装 | 参与者、触发与输入 | 用户主动执行 `dsh plugin --profile <profile> add github:Kabulaka/nova-forge#<发布标签>`。DSH 原生管理器负责解析安装目标、权限和 profile；Nova 不绕过管理器写用户配置。版本化发布包同样必须满足 bundle 加载契约。 |
| 自动挂载 | 包接口 | 包声明 `dsh.bundle.patch`，patch 自动挂载 Nova 的 DSH 入口。首次成功安装至指定 profile 后无需手工增加技能目录、配置 pluginRoot 或启用 hooks 桥；不承诺已有用户禁用设置会被升级自动改回启用。 |
| 安装范围 | 所有权与隔离 | 插件只作用于用户指定并启用它的 profile；不修改其他 profile，不创建或修改用户级、项目级 AGENTS.md，不向全局技能目录复制文件。 |
| 技能共享 | 输入、输出与资源 | DSH 从插件包内现有 `skills/` 注册五个技能；保留完整 references、assets 及跨技能控制文档，使加载结果包含可定位的技能基准目录。不得额外嵌套扫描根、复制 SOP 正文或依赖 Codex 专用元数据驱动 DSH。 |
| SOP 一致性 | 用户可见行为 | 五个技能的功能、自然语言路由、澄清、独立审查与复审、显式提交及远程操作边界沿用共享 SOP。安装和显式调用遵循各宿主原生语法；DSH 使用 `/nova-development` 等技能名，不强制仿造其他宿主的命名空间。 |
| Hook 复用 | 注入接口 | DSH 入口挂载官方 `@deepseek-ai/dsh-hooks-claude-code` 兼容桥，以安装包的绝对目录设置 `pluginRoot`，以包内 `hooks/hooks.json` 设置 `configPath`，执行现有 `hooks/run.mjs` 并读取其 `hookSpecificOutput.additionalContext`。全局规则仍以 `codex/AGENTS.global.md` 为唯一来源，不另造副本或 AGENTS.md 降级通道。 |
| 注入时机 | 顺序与不变量 | 对 `startup`、`resume`、`clear`、`compact` 四种 SessionStart 来源，等待本次 hook 完成后才允许对应会话继续请求模型。同一 SessionStart 不因重复注册而执行多次；注入上下文中的控制文档路径必须可定位到安装包内资源。 |
| 宿主交互 | 工具接口 | 共享澄清 SOP 补充 DSH 原生 `ask_user_question` 的能力映射；子代理按 DSH 当前可调用工具及已注册 provider 使用。工具错误、无交互通道和缺少独立 reviewer 的处理沿用共享 SOP，不虚构调用成功，不把无法独立审查报告为通过。 |
| 双宿主兼容 | 不变量 | Codex、Claude Code 的现有 manifest 入口、安装方式、SessionStart 配置与错误处理保持原有行为。共享文档只补充明确限定于 DSH 的必要映射；DSH 依赖不得成为现有两端加载技能和执行 hook 的额外前置条件。 |
| 包与依赖 | 资源及兼容边界 | GitHub 版本标签与发布包必须包含可直接运行的 ESM 入口、bundle patch、五个完整技能及现有 hook、规则源，安装时不要求编译或放行构建脚本。使用宿主共享的 DSH 服务依赖，避免私带第二套宿主服务；具体依赖声明遵循项目权威清单，并且仅在 DSH 入口使用。仅声明有运行验证支持的 DSH 兼容版本范围，不以静态研究推断旧版本兼容。 |
| 生命周期清理 | 禁用、卸载与并发 | 注册的技能 provider、监听器、子插件及待执行 hook 由插件作用域拥有；禁用、卸载或重新加载时释放旧注册，取消或收敛其未完成任务，禁止重复 provider、监听器或后台任务泄漏。不要求删除宿主已保存会话中的历史上下文；后续新会话不再获得本插件贡献的技能注册和注入，不清理用户从其他来源安装的技能或规则。 |
| 失败恢复 | 错误传播与重试 | 安装、包缺失、版本不兼容或适配入口挂载失败应给出可观察错误，不宣称安装功能可用，不静默改写用户文件。Hook 的输入、路径、超时及规则读取失败遵守现行双宿主边界的受控 fail open，不泄露输入或路径；恢复后由用户重试安装、启用或新开会话，不自动改动其他宿主。 |
| 升级与重复操作 | 幂等与用户配置 | 同一 profile 的重复安装、升级和重新启用不得增加重复注册或规则注入，不覆盖用户其他 bundle、配置和显式禁用选择。依赖下载与 bundle 挂载的回滚交给 DSH 管理器；Nova 不维护第二份安装台账。 |
| 实施决策 | AI 权限边界 | AI 可在已确认骨架内决定内部文件名、局部组织和测试夹具。改变支持渠道、五个技能职责、用户文件写入范围、现有两端行为、增加独立服务或进行远程发布必须重新确认。仅补充安装说明不构成发布授权。 |

## 4. 流程与复用

### 原生安装与运行

1. 用户选择 profile 及 Nova 发布标签，原生管理器安装包并应用其 bundle patch。
2. Nova 的 DSH 入口从自身模块位置解析安装根，注册包内技能 provider，并在会话初始化前挂载官方 hooks 兼容桥；无需用户配置本机绝对路径。
3. 宿主创建、恢复、清空或压缩会话时，将对应来源交给共享 SessionStart hook；模型请求等待链遵循“注入时机”契约。
4. 用户以自然语言或 DSH 原生命令使用技能；DSH 的工具映射遵循“宿主交互”契约，技能正文及控制文档按需加载。
5. 用户通过原生管理器禁用、升级或卸载 bundle；仅改变对应 profile 的后续插件行为，作用域清理遵循“生命周期清理”契约。宿主要求停止 profile 或退出 Desktop 后操作时，按其原生提示执行。

### 复用入口与依赖方向

| 已有入口 | 本次使用方式 |
|----------|--------------|
| `skills/` | 直接作为 DSH provider 的包内扫描根，不复制五个技能的规则正文 |
| `skills/nova-development/references/conversation-sop.md` | 增加宿主工具映射，保持既有问题、确认和降级语义 |
| `hooks/hooks.json`、`hooks/run.mjs` | 由官方桥执行现有 SessionStart 配置和输出协议 |
| `codex/AGENTS.global.md` | 保持唯一规则源，随包交付并由共享 hook 读取 |
| `package.json`、`scripts/check-package.mjs`、`scripts/validate-plugin.mjs` | 增加 DSH 包接口及资源完整性验证，不削弱现有双宿主约束 |
| `tests/plugin-structure.test.mjs`、`tests/hook-adapter.test.mjs`、`tests/codex-dev-plugin.test.mjs` | 复用现有回归入口，新增 DSH 原生安装和运行覆盖 |

依赖方向为“DSH 适配入口 → 官方技能 provider、官方 hooks 桥 → 现有技能与 hook 资源”。共享 hook 不反向依赖 DSH SDK；不因增加 DSH 入口而让现有两端加载它。DSH 适配器不解释或重定义五个技能的业务规则。

### 官方依据与证据边界

- [原生插件发布、bundle patch 与构建要求](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/docs/user/develop/basic/publish.md)：包级 `dsh.bundle.patch`、插件入口及 GitHub 安装约定。
- [CLI 插件管理](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/apps/cli/src/plugin.ts#L64)与[实际 bundle reconciliation](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/boot/plugin-manager/src/operations.ts#L88)：指定 profile 的安装及新 bundle 自动挂载，不能据此承诺升级自动恢复已禁用 bundle。
- [filesystem skill provider](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/skill/skill-filesystem/src/index.ts)：自定义扫描根、provider 注册及资源路径解析。
- [官方 hooks 桥](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/experimental/hooks-claude-code/src/index.ts#L209)与[Agent 初始化等待链](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/packages/core/agent/src/index.ts#L529)：初始化等待 SessionStart 回调执行完成后再释放会话请求。
- [MIT 许可证](https://github.com/deepseek-ai/deepseek-harness/blob/687f282e8625c6b8d11ff58211a90524be2e4317/LICENSE)。本文采用公开契约指导独立适配，不复制 Harness 实现。

尚未取得三端安装、模型会话、SDK 依赖组合或下表验收的运行证据；这些属于实现交付必须完成的验证，不能把设计文档作为通过证明。

## 5. 验收

使用临时 profile、临时项目及隔离的 `DSH_HOME`、`DSH_AGENTS_HOME`，同时核实 profile 实际存储位置；Codex、Claude Code 使用现有隔离方式。自动化验证不读写用户真实配置。模型请求优先使用可检查上下文的 mock 传输；真实会话验收与 mock 证据分别报告，不把 mock 请求证据作为真实宿主使用链已通过的证明。

| 覆盖契约 | 场景 | 预期结果 |
|----------|------|----------|
| 原生安装、自动挂载、包与依赖 | 从可直接运行的本地包安装，再核对 GitHub 标签安装所需的文件与元数据 | DSH 原生命令自动挂载 Nova；包内资源完整，无手工 patch、技能复制或安装时编译；远程标签未发布时如实报告尚未验证远程安装 |
| 安装范围 | 向隔离 profile 安装，另设未安装 Nova 的 profile | 仅指定 profile 获得 Nova；用户和项目 AGENTS.md、全局技能目录、其他 profile 保持原样 |
| 技能共享 | 枚举五个技能，逐个显式加载并读取技能内部和跨技能控制文档 | 名称与正文正确，资源路径指向安装包，按需引用可读，无遗漏或多余技能 |
| SOP 一致性、宿主交互 | 自然语言路由、澄清题、独立 reviewer 与同一 reviewer 复审、未授权提交或远程操作 | 采用对应技能及实际工具能力；确认、降级、独立性和操作边界与共享 SOP 一致 |
| 注入时机、Hook 复用 | 对 startup、resume、clear、compact 分别在 SessionStart 后立即请求；在允许的 hook 超时内人为延迟完成 | 捕获的对应首个请求包含正确全局规则，发生于 hook 完成之后，同一事件只执行一次 |
| 失败恢复 | 模拟无效 hook 输入、缺失插件根、规则不可读及 hook 超时 | 与现有 hook 的受控 fail open 和诊断约定一致；无秘密或输入泄露，无用户文件降级写入 |
| 原生安装、失败恢复 | 模拟不可下载版本、缺失入口或 patch、资源不完整及不兼容 SDK | 有明确失败结果，不宣称完整可用；可按宿主原生方式恢复，不破坏其他 profile 或宿主 |
| 生命周期清理、升级与重复操作 | 重复安装、升级、禁用、重新启用和卸载，并在各操作后创建新会话 | 无重复 provider、listener 或注入；禁用和卸载后的新会话不再获得本插件的技能或注入；其他来源的技能、其他 bundle 和用户禁用选择保留 |
| 生命周期清理 | 初始化中取消或退出、hook 运行中禁用、反复重载 | 旧作用域任务取消或收敛，无后台任务泄漏及卸载后继续注入；重新启用不复用已释放注册 |
| 双宿主兼容、包与依赖 | 执行现有 `npm run check`，并在隔离 Codex、Claude Code 环境验证安装、五技能发现、全局规则注入和卸载 | 现有检查与两端使用链通过；原有入口和行为保持一致，不要求 DSH SDK 或 DSH profile |
| 原生安装至生命周期清理 | 组合验证：安装 → 新会话路由 → 技能及引用加载 → 恢复/压缩 → 禁用或卸载 → 新会话 | 所有环节共同成立；分别报告结构检查、mock 请求证据、真实宿主验收及未执行项 |

本设计无待用户选择的功能差量。实施若发现官方契约、包依赖或宿主能力使上述结果无法同时成立，应停止相关改动并说明具体差量，不以削弱现有功能或验收换取通过。
