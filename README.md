# Nova Skills

一套面向 Codex 的项目治理技能，覆盖“需求澄清 → 蓝图与设计 → 实施与本地提交 → 人工 Review → 审计关闭”的完整工作流。

本仓库坚持三层事实来源：项目公共约束以 [PROJECT_BLUEPRINT.md](./PROJECT_BLUEPRINT.md) 为准，目标方案以 `docs/design/` 为准，当前实现以技能源码、脚本和测试为准。

## 核心技能

| 技能 | 用途 | 触发边界 |
|------|------|----------|
| [`nova-brainstorming`](./nova-brainstorming/) | 单问题需求澄清、项目蓝图、史诗设计、`PEND-*` / `FIX-*` / `MAINT-*` 的实施、测试与本地提交 | 需求、设计和默认开发流程 |
| [`nova-review`](./nova-review/) | 按稳定工作项选择已提交变更，复用测试证据，执行独立 Review，并在 PASS 后写入分片审计 | 仅在用户明确提出 Review、复审、补审、全部未审项或查询 Review 状态时触发 |

默认流程：

```text
需求澄清
   ↓
项目蓝图 / 史诗设计
   ↓
编码 → 测试 → 精确范围本地提交
   ↓
用户明确启动 Review
   ↓
独立审查 → 修复复审 → PASS 后关闭与审计
```

默认开发不会自动启动 Review。Git push、远程配置和 SVN commit 也不会从本地提交授权中自动推导。

## 目录结构

```text
.
├── PROJECT_BLUEPRINT.md       # 工作区公共契约与待办索引
├── codex/
│   └── AGENTS.global.md       # Codex 全局治理权威文件
├── docs/
│   ├── design/                # 史诗设计与稳定工作包锚点
│   └── audit/                 # 功能、Review 与工作项索引审计
├── nova-brainstorming/
│   ├── SKILL.md               # 需求、设计与实施入口
│   ├── references/            # 条件性 SOP 与完整示例
│   ├── assets/                # 蓝图和设计模板
│   └── scripts/               # 文档校验器及测试
└── nova-review/
    ├── SKILL.md               # 人工 Review 入口
    ├── references/            # 提交、Review 与审计契约
    └── scripts/               # 选择、预检、关闭、查询及测试
```

每个技能以 `SKILL.md` 保存触发规则和核心路由，详细流程按需从 `references/` 加载；确定性操作集中在 `scripts/`，仅依赖 Python 3 标准库。

## 安装

### 1. 克隆仓库

```bash
git clone https://github.com/Kabulaka/skills.git
cd skills
```

### 2. 建立 Codex 发现链接

```bash
mkdir -p ~/.codex/skills
ln -s "$PWD/nova-brainstorming" ~/.codex/skills/nova-brainstorming
ln -s "$PWD/nova-review" ~/.codex/skills/nova-review
ln -s "$PWD/codex/AGENTS.global.md" ~/.codex/AGENTS.md
```

工作区目录是唯一可写源码；`~/.codex` 下只保留发现链接。若目标路径已经存在，请先核对其用途和指向，再自行决定是否迁移，避免覆盖已有配置。

安装后验证：

```bash
python3 nova-review/scripts/validate_discovery.py \
  --workspace "$PWD" \
  --codex-home ~/.codex
```

## 使用

可以在 Codex 中直接描述目标，也可以显式点名技能：

```text
使用 $nova-brainstorming，帮我逐步澄清这个项目并生成项目蓝图。
```

```text
使用 $nova-brainstorming，实施 PEND-001。
```

```text
使用 $nova-review，Review PEND-001。
```

需求澄清每轮只确认一个会改变结果的信息维度；能够从代码、配置、测试或文档查明的事实会先研究，不要求用户重复提供。

## 本地验证

在仓库根目录执行：

```bash
# 校验版本 3 项目蓝图
python3 nova-brainstorming/scripts/validate_blueprint.py PROJECT_BLUEPRINT.md

# 运行两项技能的测试
python3 -m unittest discover -s nova-brainstorming/scripts -p 'test_*.py'
python3 -m unittest discover -s nova-review/scripts -p 'test_*.py'

# 校验技能与全局治理文件的发现链接
python3 nova-review/scripts/validate_discovery.py \
  --workspace "$PWD" \
  --codex-home ~/.codex
```

设计文档可单独校验：

```bash
python3 nova-brainstorming/scripts/validate_blueprint.py \
  --design docs/design/YYYY-MM-DD_example.md
```

## 关键约束

- 蓝图保存项目级公共事实，设计文档保存目标，代码、测试和配置证明当前实现。
- 已实现或已废弃的设计是不可变历史；后续演进必须新建设计并链接来源。
- 工作项使用稳定的 `PEND-*`、`FIX-*` 或 `MAINT-*` 编号，commit 只作为证据。
- 本地提交必须包含 Nova trailers；人工 Review 结论不得伪造进不可变开发提交。
- 校验器必须只读、确定性执行，并在失败时返回非零状态。

详细项目边界见 [PROJECT_BLUEPRINT.md](./PROJECT_BLUEPRINT.md)。
