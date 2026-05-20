# 在 ZeroClaw、IronClaw、openclaw 里安装 hardware-event-observe

这份说明只覆盖 claw toolkit 侧的 skill 打包方式、默认运行时目录和环境变量约定。

如果你要看完整的跨机器安装流程，先看 [docs/guide.md](docs/guide.md)。如果你只关心 Ironclaw 的交互命令示例，再看 [docs/ironclaw.md](docs/ironclaw.md)。

当前仓库里有两份同内容的 skill 目录：

- `skills/hardware-event-observe/`：给 ZeroClaw、IronClaw、openclaw 这类安装命令直接扫描仓库根目录时使用
- `.github/skills/hardware-event-observe/`：给 VS Code / Copilot Skill 发现机制使用

## 支持的全局目录布局

- ZeroClaw：`~/.zeroclaw/skills/hardware-event-observe`
- IronClaw：`~/.ironclaw/skills/hardware-event-observe`
- openclaw：`~/.openclaw/skills/hardware-event-observe`

只要 skill 被真实复制到这些目录之一，helper 脚本就会把对应目录识别成当前 toolkit 的 home，而不是再额外嵌套一层 `.openclaw`。

## 默认运行时目录

- ZeroClaw 全局安装：`~/.zeroclaw/perf-skill/venv`
- IronClaw 全局安装：`~/.ironclaw/perf-skill/venv`
- openclaw 全局安装：`~/.openclaw/perf-skill/venv`
- 任意 workspace 安装到 `./skills/`：`./.openclaw/perf-skill/venv`

FlameGraph 仓库也会跟着当前 `PERF_SKILL_HOME` 走，例如 IronClaw 全局安装默认会落到 `~/.ironclaw/perf-skill/FlameGraph`。

## 最小安装步骤

1. 进入仓库根目录。

```bash
cd /path/to/perf_skill
```

2. 选定一个 toolkit home，并把 skill 复制进去。

```bash
export CLAW_HOME=~/.ironclaw
mkdir -p "$CLAW_HOME/skills"
rm -rf "$CLAW_HOME/skills/hardware-event-observe"
cp -r skills/hardware-event-observe "$CLAW_HOME/skills/"
```

如果你要换成 ZeroClaw 或 openclaw，只需要把上面的 `CLAW_HOME` 改成 `~/.zeroclaw` 或 `~/.openclaw`。

3. 如果你希望 toolkit 里的 skill 明确使用当前仓库源码，再设置本地仓库根目录。

```bash
export PERF_SKILL_REPO="$PWD"
```

4. 第一次触发 skill 后，确认对应 runtime 目录已经自动生成。

```bash
test -x "$CLAW_HOME/perf-skill/venv/bin/python3"
```

如果你走的是 IronClaw，可以继续按 [docs/ironclaw.md](docs/ironclaw.md) 里的命令启动和触发 skill。ZeroClaw 或 openclaw 的具体交互命令以各自 toolkit 的 CLI 为准，但目录布局和 runtime 规则与这里一致。

## 环境变量优先级

- `PERF_SKILL_HOME`：最高优先级，直接指定 `perf-skill` 的共享根目录
- `ZEROCLAW_HOME`、`IRONCLAW_HOME`、`OPENCLAW_HOME`：只指定 toolkit home，让 helper 自动推导到对应的 `perf-skill/`
- `PERF_SKILL_VENV_DIR`：只改 Python 虚拟环境目录
- `PERF_SKILL_FLAMEGRAPH_DIR`：只改 FlameGraph 仓库目录
- `PERF_SKILL_PACKAGE_SOURCE`：本地仓库源码不可见时，指定 Python 包安装来源

例如：

```bash
export IRONCLAW_HOME=/srv/.ironclaw
export PERF_SKILL_VENV_DIR=/srv/runtime/perf-skill-venv
```

如果你不是通过 helper 脚本启动，而是直接运行 `python3 -m perf_skill`，又希望默认目录跟 ZeroClaw 或 IronClaw 对齐，记得先设置对应的 `*_HOME` 或 `PERF_SKILL_HOME`。

## 注意事项

- `PERF_SKILL_REPO` 只影响是否使用当前仓库源码，不改变 runtime 根目录
- IronClaw 已确认会跳过 `~/.ironclaw/skills` 下的符号链接，因此建议始终使用真实复制；其他 toolkit 如果也会跳过符号链接，同样遵循这个做法
- 统一切换目录布局时，优先改 `PERF_SKILL_HOME`；只有在你明确想保留 toolkit home 语义时，再分别设置 `ZEROCLAW_HOME`、`IRONCLAW_HOME` 或 `OPENCLAW_HOME`