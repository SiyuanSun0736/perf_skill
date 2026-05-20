# 在 Ironclaw 里使用 hardware-event-observe

这份仓库里的 skill 目录在 .github/skills/hardware-event-observe，但 Ironclaw 不会直接扫描这个位置。要在 Ironclaw 里使用它，需要先把 skill 安装到 Ironclaw 自己的 skills 目录，再从当前仓库启动 Ironclaw。

## 先决条件

- Linux 环境
- 已安装 ironclaw、python3、perf
- 如果是第一次使用 Ironclaw，先完成初始化

```bash
ironclaw onboard
ironclaw models status
```

如果还没有默认模型，可以继续检查和设置：

```bash
ironclaw models list
ironclaw models set-provider <PROVIDER>
ironclaw models set <MODEL>
```

## 1. 安装 skill 到 Ironclaw

先进入这个仓库根目录：

```bash
cd /path/to/perf_skill
```

然后把 skill 真实复制到 Ironclaw 的 skills 目录：

```bash
mkdir -p ~/.ironclaw/skills
cp -r .github/skills/hardware-event-observe ~/.ironclaw/skills/
ironclaw skills info hardware-event-observe
```

不要用软链接。当前版本的 Ironclaw 会跳过 ~/.ironclaw/skills 里的符号链接，所以像下面这种方式不会生效：

```bash
ln -s "$PWD/.github/skills/hardware-event-observe" ~/.ironclaw/skills/hardware-event-observe
```

如果你之前已经装过旧版本，先删除旧目录再复制一遍：

```bash
rm -rf ~/.ironclaw/skills/hardware-event-observe
cp -r .github/skills/hardware-event-observe ~/.ironclaw/skills/
```

## 2. 可选：让 skill 使用本地仓库源码

因为 Ironclaw 会把 skill 放在 ~/.ironclaw/skills 下运行，而不是直接在仓库里运行，所以“使用本地源码 checkout”现在是一个显式可选项，而不是必需项：

```bash
cd /path/to/perf_skill
export PERF_SKILL_REPO="$PWD"
```

现在有两种模式：

- 直接运行：不设置 `PERF_SKILL_REPO` 也可以。脚本会自动创建运行时环境，并从默认包来源安装 `perf-skill`
- 本地源码开发：如果你希望 Ironclaw 明确跑当前机器上的仓库源码，再设置 `PERF_SKILL_REPO`

## 3. 启动 Ironclaw

交互模式：

```bash
ironclaw run
```

单条消息模式：

```bash
ironclaw run -m "追踪 comm=node pid=16874 的 inst 和 cycles，先 dry-run" --auto-approve
```

如果你要强制走本地源码模式，再在上面两条命令前加：

```bash
cd /path/to/perf_skill
export PERF_SKILL_REPO="$PWD"
```

## 4. 怎么触发这个 skill

当前版本的 ironclaw run 没有类似 --skill hardware-event-observe 这样的显式参数。它会先自动加载 ~/.ironclaw/skills 里的 skill，然后根据你的消息内容决定是否触发。

为了让命中更稳定，建议直接把目标和事件写完整，尽量沿用这个 skill 已支持的表达：

- trace comm=node pid=16874 inst cycles
- observe pid=16874 cache-misses branches
- 追踪 comm=nginx pid=31337 的 inst 和 cycles
- watch pid 9001 events=inst,cycles,cache-misses

你也可以在消息里顺手点名它，例如：

```text
请使用 hardware-event-observe，先 dry-run：追踪 pid=16874 的 inst、cycles 和 cache-misses
```

## 5. 常用示例

先看解析结果和生成的 perf 命令：

```text
追踪 comm=node pid=16874 的 inst 和 cycles，先 dry-run
```

做一次真实采样并输出单行结果：

```text
observe pid=16874 cache-misses branches --samples 5 --plain
```

导出 CSV 和 SVG：

```text
observe pid=16874 branch-misses --samples 10 --csv-out out/node.csv --svg-out out/node.svg
```

如果你要用 --svg-out，建议先在当前 Python 环境里安装项目依赖：

```bash
cd /path/to/perf_skill
python3 -m pip install -e .
```

## 6. 常见问题

### ironclaw skills info 看不到 hardware-event-observe

通常有两个原因：

- 你还没把目录复制到 ~/.ironclaw/skills
- 你用了 ln -s，Ironclaw 把这个软链接跳过了

### 运行时报 No module named perf_skill

如果你想强制让 skill 使用本地源码，先回到仓库根目录，再设置：

```bash
cd /path/to/perf_skill
export PERF_SKILL_REPO="$PWD"
```

如果你不想依赖源码路径，也可以让脚本自己自动引导，或者直接把包安装到当前 Python 环境：

```bash
cd /path/to/perf_skill
python3 -m pip install -e .
```

### perf 报权限问题

这是 perf 本身的权限限制，不是 skill 的问题。常见处理方式是调整 kernel.perf_event_paranoid，或者在有权限的环境里运行。

### comm 匹配到多个进程

这个 skill 不会自动替你切到别的进程。遇到歧义时，直接补一个 pid 即可。