# 在其他机器上安装和使用 hardware-event-observe

这份文档说明怎样把本仓库里的 `hardware-event-observe` skill 带到另一台 Linux 机器上，并在 VS Code 或 Ironclaw 里实际跑起来。

它覆盖两种用法：

- 方式 A：在 VS Code + GitHub Copilot Chat 里，直接使用仓库内的 workspace skill
- 方式 B：在 Ironclaw 里，把 skill 复制到 `~/.ironclaw/skills` 后使用

如果你只是想在另一台机器上直接跑 CLI，而不是通过 skill 触发，也可以看文末的“只安装 CLI”小节。

## 先知道这套东西是怎么工作的

这个 skill 的定义在：

```text
.github/skills/hardware-event-observe/
```

skill 实际调用的是这个 helper 脚本：

```bash
bash .github/skills/hardware-event-observe/scripts/run-observe.sh ...
```

这个脚本会做三件事：

- 如果本地能看到仓库源码，就直接使用当前仓库，或者使用你显式设置的 `PERF_SKILL_REPO`
- 如果 skill 是装在当前工作区的 `./skills/` 下，就把运行时默认放到 `./.openclaw/perf-skill/`
- 如果 skill 是装在全局 `~/.openclaw/skills/` 下，就把运行时默认放到 `~/.openclaw/perf-skill/`
- 找不到本地仓库源码时，会改从 `PERF_SKILL_PACKAGE_SOURCE` 安装 Python 包；默认来源是 skill 自带的 PyPI requirement

这意味着大多数情况下，你不需要先手工执行 `pip install -e .`。只要 `python3 -m venv` 可用，第一次跑 skill 时它会自己把运行时环境补起来；是否走本地源码模式，取决于当前机器上能不能直接看到这个仓库。

## Workspace 和 Global 安装是怎么落地的

这套行为不是靠 `release.yml` 决定的，而是靠“skill 实际被安装到哪里”加上 helper 脚本自己的路径判断实现的。

- 如果 skill 目录在当前项目的 `./skills/hardware-event-observe/` 下，脚本会把这个项目根目录当作当前 workspace，并默认把运行时放到 `./.openclaw/perf-skill/`
- 如果 skill 目录在 `~/.openclaw/skills/hardware-event-observe/` 下，脚本会把 `~/.openclaw` 当作全局共享根目录，并默认把运行时放到 `~/.openclaw/perf-skill/`
- 如果你直接在本仓库里运行 `.github/skills/hardware-event-observe/` 这份源码版 skill，脚本会优先找到仓库根目录，并以 editable 模式安装本地源码

也就是说：

- Workspace 隔离，靠的是 skill 被安装在当前工作区自己的 `./skills` 下面
- Global 共享，靠的是 skill 被安装在用户级的 `~/.openclaw/skills` 下面
- Python 运行时是否隔离，取决于默认的 `OPENCLAW_HOME` 落在哪里；workspace 模式默认是当前项目内的 `./.openclaw`，global 模式默认是 `~/.openclaw`

## 要不要上架，或者改 release.yml

如果你只是手工复制 skill，或者让 OpenClaw 从某个已知来源把它安装到 `./skills` 或 `~/.openclaw/skills`，不需要改 `release.yml`。

只有下面两类需求，才需要额外的发布动作：

- 你想让 `openclaw skills install <技能名>` 这种“按名字安装”的命令可以直接找到它。这通常意味着要把 skill 发布到 OpenClaw/ClawHub 能索引到的 skill registry、marketplace，或者其他它原生支持的分发源。
- 你想把 Python 包的安装源固定成某个 release 资产、wheel、sdist 或 PyPI 版本。这时才需要额外维护发布产物，或者在 CI 里自动生成 release 资产。

对这个仓库本身来说，当前默认路径已经切到 PyPI：skill 会自带一个和 release 版本绑定的 requirement，例如 `perf-skill==当前版本`，helper 脚本在没有本地源码 checkout 时会直接按这个 requirement 安装。GitHub Release 仍然保留构建产物；如果你想改用内部制品库、wheel URL 或 release 资产，再覆盖 `PERF_SKILL_PACKAGE_SOURCE` 即可。

## 先决条件

目标机器需要满足这些条件：

- Linux 环境
- 已安装 `git`
- 已安装 `python3`
- `python3 -m venv` 可用
- 已安装 `perf`

如果你要在 VS Code 里用，还需要：

- VS Code
- GitHub Copilot Chat

如果你要在 Ironclaw 里用，还需要：

- `ironclaw` 已安装
- 已完成基础模型配置

你可以先做一个最小检查：

```bash
command -v git
command -v python3
python3 -m venv --help >/dev/null
command -v perf
```

如果这里失败，先把系统依赖补齐，再继续后面的步骤。

## 方式 A：在 VS Code 里直接使用这个 skill

这是最简单的路径。因为 skill 已经跟仓库一起放在 `.github/skills/` 下面，只要你在另一台机器上把仓库 clone 下来并用 VS Code 打开，Copilot Chat 就能看到它。

### 1. clone 仓库

```bash
git clone https://github.com/SiyuanSun0736/perf_skill.git
cd perf_skill
```

### 2. 用 VS Code 打开这个仓库

直接打开仓库根目录即可，不需要把 skill 额外复制到别的地方。

### 3. 先做一次无目标 smoke test

这个命令不需要先准备 PID，适合验证脚本、Python 环境和 `perf` 事件枚举链路是否通了：

```bash
bash .github/skills/hardware-event-observe/scripts/run-observe.sh events branch
```

第一次运行时，如果你看到它自动创建 `~/.openclaw/perf-skill/venv`，这是正常行为。

如果你是把 skill 装进当前项目的 `./skills/`，那么默认生成的位置会变成当前项目里的 `./.openclaw/perf-skill/venv`。

### 4. 在 VS Code Chat 里触发 skill

示例：

```text
/hardware-event-observe 追踪 pid=4242 的 inst 和 cycles，先 dry-run
/hardware-event-observe observe pid=4242 branch-misses --samples 5 --plain
/hardware-event-observe 解析 out/target.data 并生成火焰图
```

建议第一次先用 `dry-run`，先看解析结果和最终会执行的 `perf` 命令，再做真实采样。

## 方式 B：在 Ironclaw 里安装和使用这个 skill

Ironclaw 不会直接扫描仓库里的 `.github/skills`，所以要多做一步复制。

### 1. clone 仓库

```bash
git clone https://github.com/SiyuanSun0736/perf_skill.git
cd perf_skill
```

### 2. 把 skill 复制到 Ironclaw 的 skills 目录

```bash
mkdir -p ~/.ironclaw/skills
rm -rf ~/.ironclaw/skills/hardware-event-observe
cp -r .github/skills/hardware-event-observe ~/.ironclaw/skills/
```

不要用软链接。当前版本的 Ironclaw 会跳过 `~/.ironclaw/skills` 下的符号链接。

### 3. 可选：告诉脚本仓库根目录在哪里

```bash
cd /path/to/perf_skill
export PERF_SKILL_REPO="$PWD"
```

这一步现在是可选的，不再是必需步骤。

- 如果你只是想让 skill 在另一台机器上跑起来，脚本可以直接自举 Python 运行时，不要求本机一定先有这个仓库的源码 checkout
- 如果你希望它明确使用某个本地源码仓库，并以 editable 模式安装，这时再设置 `PERF_SKILL_REPO`

### 4. 确认 Ironclaw 看得到这个 skill

```bash
ironclaw skills info hardware-event-observe
```

### 5. 启动并触发 skill

交互模式：

```bash
ironclaw run
```

单条消息模式：

```bash
ironclaw run -m "请使用 hardware-event-observe，先 dry-run：追踪 pid=4242 的 inst 和 cycles" --auto-approve
```

## 首次运行时会发生什么

第一次成功执行 skill 时，helper 脚本会自动：

- 按安装位置选择运行时目录：workspace 模式默认是 `./.openclaw/perf-skill/venv`，global 模式默认是 `~/.openclaw/perf-skill/venv`
- 能看到本地仓库时，以 editable 模式安装当前仓库；看不到本地仓库时，从 skill 自带的 PyPI requirement 安装对应版本的 Python 包
- 当你第一次请求 FlameGraph 时，在当前 `PERF_SKILL_HOME` 下 clone FlameGraph

如果后续你在这台机器上更新了仓库代码，editable 安装会直接看到源码变化。

如果 `pyproject.toml`、`SKILL.md` 或 helper 脚本本身发生变化，或者运行时缺依赖，脚本也会在下一次运行时自动重装环境。

## 升级到新版本怎么做

如果另一台机器上的仓库已经存在，常规更新步骤是：

```bash
cd /path/to/perf_skill
git pull
```

如果你走的是 VS Code workspace skill 路径，到这里通常就够了。

如果你走的是 Ironclaw 路径，还建议把 skill 目录重新复制一遍，确保 `SKILL.md`、脚本和其他元数据也跟着更新：

```bash
cd /path/to/perf_skill
rm -rf ~/.ironclaw/skills/hardware-event-observe
cp -r .github/skills/hardware-event-observe ~/.ironclaw/skills/
```

然后再执行一次任意命令，例如：

```bash
bash .github/skills/hardware-event-observe/scripts/run-observe.sh events branch
```

如果你怀疑另一台机器上的自动引导环境已经脏了，可以手工删掉它，让脚本下一次重新创建：

```bash
rm -rf ~/.openclaw/perf-skill/venv
```

## 常用验证命令

### 1. 不依赖目标进程，先验证 skill 链路

```bash
bash .github/skills/hardware-event-observe/scripts/run-observe.sh events cache
```

### 2. 先看 dry-run

```bash
bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "trace pid=4242 inst cycles" --dry-run
```

### 3. 做一次真实采样

```bash
bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "trace pid=4242 branch-misses cache-misses" --samples 5 --plain
```

### 4. 解析现成的 perf.data

```bash
bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "解析 out/target.data" --summary
```

## 常用环境变量

如果你要在另一台机器上自定义目录布局，这几个环境变量最有用：

- `PERF_SKILL_REPO`：显式指定本地仓库根目录；只在你要强制走本地源码模式时需要
- `OPENCLAW_HOME` 或 `PERF_SKILL_HOME`：修改运行时根路径；workspace 模式和 global 模式都会受它影响
- `PERF_SKILL_VENV_DIR`：只修改自动创建的 Python 虚拟环境路径
- `PERF_SKILL_FLAMEGRAPH_DIR`：只修改 FlameGraph 仓库路径
- `PERF_SKILL_PACKAGE_SOURCE`：在没有本地仓库源码时，指定 Python 包安装来源，可以是 PyPI requirement、git URL、wheel、sdist 或本地路径

例如：

```bash
export PERF_SKILL_REPO=/srv/perf_skill
export PERF_SKILL_HOME=/srv/.openclaw/perf-skill
export PERF_SKILL_PACKAGE_SOURCE='perf-skill==<release-version>'
```

## 常见问题

### 运行时报 `could not locate the perf-skill repository root`

旧版本脚本才会报这个错误。现在如果没有本地仓库，默认会改从 `PERF_SKILL_PACKAGE_SOURCE` 安装。

如果你仍然遇到类似问题，优先检查这两点：

- 你是否显式设置了错误的 `PERF_SKILL_REPO`
- 你配置的 `PERF_SKILL_PACKAGE_SOURCE` 是否可访问

### 运行时报 `No module named perf_skill`

优先检查脚本刚刚安装的运行时是不是成功，或者你给的本地源码路径是否正确。

如果你要强制走本地源码模式，可以回到仓库根目录，并设置：

```bash
export PERF_SKILL_REPO="$PWD"
```

如果你不想依赖自动引导，也可以手工安装：

```bash
python3 -m pip install -e .
```

### 运行时报 `failed to create virtual environment with python3 -m venv`

说明目标机器缺少 venv 支持。先让这条命令能正常工作：

```bash
python3 -m venv /tmp/perf-skill-test-venv
rm -rf /tmp/perf-skill-test-venv
```

如果失败，先安装系统的 Python venv 组件，再重试。

### Ironclaw 看不到 `hardware-event-observe`

通常只有两个原因：

- 你还没把目录复制到 `~/.ironclaw/skills`
- 你用了软链接而不是实际目录复制

### `perf` 报权限问题或 `<not counted>`

这不是 skill 自己的安装问题，而是 `perf` 的运行限制。常见原因是：

- `kernel.perf_event_paranoid` 太高
- 当前环境是容器、虚拟机或 WSL，硬件事件受限
- 当前用户没有足够权限

### `comm` 匹配到多个进程

这个 skill 不会默默替你切换到别的进程。遇到歧义时，直接补一个明确的 `pid`。

## 只安装 CLI，不通过 skill 触发

如果你在另一台机器上不需要 VS Code Chat 或 Ironclaw，只想直接用命令行：

```bash
git clone https://github.com/SiyuanSun0736/perf_skill.git
cd perf_skill
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e .
perf-skill observe "trace pid=4242 inst cycles" --dry-run
```

这条路径安装的是 CLI，本质上和 skill 最终调用的核心逻辑是同一套代码。