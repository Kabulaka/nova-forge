# Nova Skills

一套面向 Codex 的项目治理技能，覆盖“总体需求 → 并行架构契约 → 功能开发与本地提交 → 人工 Review → 审计关闭”的完整工作流。

本仓库坚持分层事实来源：总体业务以 `.nova/PRODUCT_REQUIREMENTS.md` 与需求块为准，公共技术约束以 [.nova/PROJECT_BLUEPRINT.md](.nova/PROJECT_BLUEPRINT.md) 与架构契约为准，已实现复用入口以 `.nova/SHARED_CAPABILITIES.md` 为索引，目标方案以 `.nova/design/` 为准，当前实现以技能源码、脚本和测试为准。

## 核心技能

| 技能 | 用途 | 触发边界 |
|------|------|----------|
| [`nova-requirements`](./nova-requirements/) | 总体业务、业务模块和可独立交付需求块 | 绿地项目、新需求或业务语义变化 |
| [`nova-architecture`](./nova-architecture/) | 技术栈、七章蓝图与 API/数据/事件/Mock 并行契约 | 绿地初始化或共享架构变化 |
| [`nova-development`](./nova-development/) | 功能设计、`PEND-*` / `FIX-*` / `MAINT-*` 的实施、测试与本地提交 | 已确认需求下的功能和普通开发 |
| [`nova-doctor`](./nova-doctor/) | 只读检查当前项目的 Nova 数据、引用、审计与迁移状态 | 项目健康检查、校验失败诊断或迁移判断 |
| [`nova-review`](./nova-review/) | 按稳定工作项选择已提交变更，复用测试证据，执行独立 Review，并在 PASS 后写入分片审计 | 仅在用户明确提出 Review、复审、补审、全部未审项或查询 Review 状态时触发 |

默认流程：

```text
总体需求与独立需求块
   ↓
项目蓝图与并行架构契约
   ↓
功能设计 → 编码 → 测试 → 精确范围本地提交
   ↓
用户明确启动 Review
   ↓
独立审查 → 修复复审 → PASS 后关闭与审计
```

默认开发不会自动启动 Review。Git push、远程配置和 SVN commit 也不会从本地提交授权中自动推导。

## 目录结构

```text
.
├── .nova/
│   ├── PRODUCT_REQUIREMENTS.md # 总体业务与需求索引（按需）
│   ├── PROJECT_BLUEPRINT.md    # 公共技术契约与待办索引
│   ├── SHARED_CAPABILITIES.md  # 已实现共享能力及源码位置（按需）
│   ├── requirements/           # 长期需求块（按需）
│   ├── architecture/           # 并行开发前置契约（按需）
│   ├── design/                 # 功能设计与稳定工作包锚点
│   └── audit/                  # 功能、Review 与工作项索引审计
├── codex/
│   ├── AGENTS.global.md        # Codex 与 Claude Code 共用的全局治理权威文件
│   └── scripts/                # 双宿主安装器及全局规则契约测试
├── nova-requirements/          # 需求访谈、模板、示例和校验
├── nova-architecture/          # 架构访谈、模板、示例和校验
├── nova-development/
│   ├── SKILL.md               # 需求、设计与实施入口
│   ├── references/            # 条件性 SOP 与完整示例
│   ├── assets/                # 蓝图和设计模板
│   └── scripts/               # 文档校验器及测试
├── nova-doctor/
│   ├── SKILL.md               # 当前项目只读健康检查入口
│   └── scripts/               # 聚合诊断脚本及测试
└── nova-review/
    ├── SKILL.md               # 人工 Review 入口
    ├── references/            # 提交、Review 与审计契约
    └── scripts/               # 选择、预检、关闭、查询及测试
```

每个技能以 `SKILL.md` 保存触发规则和核心路由，详细流程按需从 `references/` 加载；确定性操作集中在 `scripts/`，仅依赖 Python 3 标准库。

## 安装

### 1. 克隆仓库

```bash
git clone https://github.com/Kabulaka/nova-forge.git
cd nova-forge
```

### 2. 安装 Codex 与 Claude Code 用户级发现链接

Codex 从 `~/.codex/AGENTS.md` 加载用户级规则，Claude Code 从 `~/.claude/CLAUDE.md` 加载用户级规则；两者都指向本仓库唯一的 `codex/AGENTS.global.md`。五个 Nova 技能也会分别链接到两个宿主的用户级技能目录。

运行统一安装器：

```bash
python3 codex/scripts/install_global_rules.py
```

安装器会先检查全部目标，再开始修改：

- 已存在的正常或失效软链接会先解除链接本身，再指向当前仓库；不会删除原链接指向的文件或目录。
- 任一目标是普通文件或真实目录时，安装整体失败且不修改其他入口；请先核对其用途，再自行决定是否迁移或合并。
- 仓库迁移或更换克隆目录后，重新执行同一命令即可刷新全部链接。
- 工作区目录始终是唯一实体源码，两个宿主的用户目录只保存发现链接。

链接更新后请分别新开 Codex 和 Claude Code 会话，使用户级规则与技能重新加载。

确认两个用户级规则入口都解析到当前仓库：

```bash
readlink -f ~/.codex/AGENTS.md
readlink -f ~/.claude/CLAUDE.md
```

两个输出都应为当前仓库下 `codex/AGENTS.global.md` 的绝对路径，而不是旧克隆目录。

安装后验证：

```bash
python3 nova-review/scripts/validate_discovery.py \
  --workspace "$PWD" \
  --codex-home ~/.codex \
  --claude-home ~/.claude
```

## 使用

可以在 Codex 或 Claude Code 中直接描述目标，也可以显式点名技能：

```text
使用 $nova-requirements，帮我逐步澄清这个项目的总体业务和需求块。
```

```text
使用 $nova-architecture，基于已确认需求生成最小架构和并行开发契约。
```

```text
使用 $nova-development，实施 PEND-001。
```

```text
使用 $nova-doctor，只读检查当前项目的 Nova 健康状态。
```

```text
使用 $nova-review，Review PEND-001。
```

需求澄清每轮只确认一个会改变结果的信息维度；能够从代码、配置、测试或文档查明的事实会先研究，不要求用户重复提供。

## 本地验证

在仓库根目录执行：

```bash
# 校验版本 3 项目蓝图
python3 nova-development/scripts/validate_blueprint.py .nova/PROJECT_BLUEPRINT.md

# 共享能力目录存在时，校验登记项及源码位置
python3 nova-architecture/scripts/validate_shared_capabilities.py --if-present .nova/SHARED_CAPABILITIES.md

# 运行各技能测试
python3 -m unittest discover -s codex/scripts -p 'test_*.py'
python3 -m unittest discover -s nova-requirements/scripts -p 'test_*.py'
python3 -m unittest discover -s nova-architecture/scripts -p 'test_*.py'
python3 -m unittest discover -s nova-development/scripts -p 'test_*.py'
python3 -m unittest discover -s nova-doctor/scripts -p 'test_*.py'
python3 -m unittest discover -s nova-review/scripts -p 'test_*.py'

# 只读检查当前项目的 Nova 数据
python3 nova-doctor/scripts/nova_doctor.py

# 校验技能与全局治理文件的发现链接
python3 nova-review/scripts/validate_discovery.py \
  --workspace "$PWD" \
  --codex-home ~/.codex \
  --claude-home ~/.claude
```

设计文档可单独校验：

```bash
python3 nova-development/scripts/validate_blueprint.py \
  --design .nova/design/YYYY-MM-DD_example.md
```

## 关键约束

- 蓝图保存项目级公共事实，设计文档保存目标，代码、测试和配置证明当前实现。
- 开发澄清先查共享能力目录与实际代码；新增共享能力由用户确认，最低验收后才登记。
- 模块业务表、查询和 Repository 归模块所有，但代码落位和依赖方向必须服从蓝图分层。
- 已实现或已废弃的设计是不可变历史；后续演进必须新建设计并链接来源。
- 工作项使用稳定的 `PEND-*`、`FIX-*` 或 `MAINT-*` 编号，commit 只作为证据。
- 本地提交必须包含 Nova trailers；人工 Review 结论不得伪造进不可变开发提交。
- 校验器必须只读、确定性执行，并在失败时返回非零状态。

详细项目边界见 [.nova/PROJECT_BLUEPRINT.md](.nova/PROJECT_BLUEPRINT.md)。
