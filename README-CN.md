# perf-skill

[English](./README.md) | [简体中文](./README-CN.md)

perf-skill 是一个面向 Linux 的 CLI 工具，用来把简短的声明式指令转换成可直接运行的 `perf stat` 观测会话。它会自动解析目标进程、补齐常用 PMU 默认项，并实时输出带 IPC 和最近时序的终端观测结果。

## 功能概览

- 解析类似 `trace comm=python pid=4242 inst cycles` 的声明式语句
- 根据 `pid`、`comm` 或两者组合解析目标进程
- 支持事件别名转换，例如 `inst -> instructions`
- 无论是否显式指定，都会补齐 `instructions` 和 `cycles`，保证可以计算 IPC
- 自动补齐事件配对，例如 `branches + branch-misses`、`cache-references + cache-misses`
- 自动把相关事件放进 perf group，保证 IPC、分支和缓存计数尽量保持对齐
- 根据 PMU slot 上限自动拆组，并结合本机硬件信息或厂商启发式做默认值推断
- 当 perf 对某个 group 返回可重试错误时，只拆失败的 group，不重跑整批事件
- 解析 `perf stat` 的区间采样输出并实时展示
- 支持导出 CSV 与 SVG 时序图
- 提供 ASCII 终端仪表板和单行 plain 输出两种显示模式

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install .
perf-skill observe "trace comm=python pid=4242 inst cycles"
```

如果是本地开发模式，建议使用：

```bash
pip install -e .[dev]
```

第一次使用建议先跑 `--dry-run`，先看解析结果和生成的 `perf` 命令，再决定是否真正附着到目标进程。

```bash
perf-skill observe "trace python 4242 inst" --dry-run
```

默认情况下，CLI 会使用 `--group-mode auto` 生成 `perf stat -e` 的事件分组，例如：

- `{instructions,cycles,cache-misses}`
- `{instructions,cycles},{branches,branch-misses}`

这样能尽量把相关计数器放在同一个 perf group 中，而不是把所有事件都硬塞进一个过大的集合。

如果你想关闭分组，可以用：

```bash
perf-skill observe "trace pid=4242 inst cycles" --group-mode off
```

如果你想强制按固定大小切组，可以用：

```bash
perf-skill observe "trace pid=4242 inst cycles branches cache-misses" --group-mode always
```

`--pmu-slots auto` 会优先读取本机 PMU 元数据，再回退到厂商启发式，例如常见 Intel 核心默认 `4`，较新的 AMD Zen 系列默认 `6`。也可以手动覆盖：

```bash
perf-skill observe "trace pid=4242 inst cycles" --pmu-slots 4
```

如果 grouped collection 失败，例如遇到 `<not counted>` 或 perf 的 group 调度类错误，CLI 会自动缩小失败 group 的 slot 上限，最后必要时回退到非 group 模式。已经成功的 group 会保持原样，不会被一起降级。关闭这个行为可以使用：

```bash
perf-skill observe "trace pid=4242 branch-misses cache-misses" --no-group-retry
```

你可以用下面两个命令查看完整帮助：

```bash
perf-skill --help
perf-skill observe --help
```

## 支持的声明式语句

当前解析器是刻意做成“窄而稳定”的，不追求任意自然语言都能猜中。

支持的形式包括：

- `trace comm=python pid=4242 inst cycles`
- `observe python 4242 instructions`
- `追踪 comm=nginx pid=31337 inst cycles`
- `watch pid 9001 events=inst,cycles,cache-misses`

支持的目标键：

- `pid`，例如 `pid=1234`
- `comm`，例如 `comm=python`

支持的事件别名：

- `inst`、`instruction`、`instructions`
- `cycle`、`cycles`
- `branch-misses`、`branches`
- `cache-misses`、`cache-references`

即使你只请求了 `cache-misses` 或 `branches`，工具也会保留 `instructions` 和 `cycles`，确保 IPC 始终可用。

即使你只写了 `branch-misses` 或 `cache-misses`，CLI 也会补齐对应配对事件，方便得到更可解释的时间序列结果。

自动分组规则：

- `instructions` 和 `cycles` 会优先放在同一个核心 group 中
- 如果同时存在，`branches` 和 `branch-misses` 会被放进同一组
- 如果同时存在，`cache-references` 和 `cache-misses` 会被放进同一组
- 剩余的单个事件会尽量塞进还有容量的组里

## 导出时序数据

采样过程中导出 CSV：

```bash
perf-skill observe "trace pid=4242 inst cycles cache-misses" \
  --samples 10 --plain --csv-out out/samples.csv
```

同时导出 CSV 和 SVG：

```bash
perf-skill observe "trace pid=4242 inst cycles branches" \
  --samples 20 --plain --csv-out out/samples.csv --svg-out out/timeline.svg
```

CSV 是每个采样区间一行。SVG 是一个按指标分面板堆叠的时序报告，若 IPC 可计算，也会单独画出来。

现在 SVG 图是通过 matplotlib 渲染的，而不是手写 XML，因此图表观感和后续维护性都会更好。

如果你想让 SVG 更紧凑，可以关闭图例：

```bash
perf-skill observe "trace pid=4242 inst cycles" --svg-out out/timeline.svg --no-svg-legend
```

## 打包与发布

本地构建 wheel 和 sdist：

```bash
python -m pip install -e .[dev]
python -m build
```

本地安装生成的 wheel：

```bash
pip install dist/perf_skill-*.whl
```

仓库里已经包含一个基于 tag 触发的 GitHub Actions 发布流程，位置在：

```text
.github/workflows/release.yml
```

推送类似 `v0.5.0` 这样的 tag 时，workflow 会执行：

- 构建 wheel 和 sdist
- 校验 tag 与 `perf_skill.__version__` 是否一致
- 根据上一个 tag 到当前 tag 的提交区间生成 changelog
- 上传构建产物
- 创建 GitHub Release 并附带构建产物

当前发布流程使用两个辅助脚本：

- `scripts/release/validate_tag.py`：校验 `vX.Y.Z` 与包版本一致
- `scripts/release/generate_changelog.py`：根据 tag 区间生成 release notes

如果你想开启 PyPI 发布，需要先在 PyPI 上把这个仓库配置成 trusted publisher，并设置仓库变量：

```text
PUBLISH_PYPI=true
```

配置完成后，tag 构建会在 GitHub Release 之后继续把相同的 `dist/` 产物发布到 PyPI。

也可以本地手动运行这两个发布脚本：

```bash
PYTHONPATH=src python3 scripts/release/validate_tag.py v0.5.0
PYTHONPATH=src python3 scripts/release/generate_changelog.py --tag v0.5.0 --output /tmp/release-notes.md
```

## 注意事项

- 仅支持 Linux，底层依赖 `perf`
- 可能需要更低的 `kernel.perf_event_paranoid` 或更高权限
- 如果 `comm` 匹配到多个进程，工具会要求你补充 `pid`
- 终端仪表板是 ASCII 输出，在交互式 TTY 下效果最好

## 开发

运行单元测试：

```bash
python -m unittest discover -s tests
```

## IDE 用法

这个仓库还带了一份 Copilot Skill，位置在：

```text
.github/skills/hardware-event-observe/
```

这样你可以直接在 VS Code Chat 里用自然语言触发本地 CLI。

示例：

```text
/hardware-event-observe 追踪 comm=node pid=16874 的 inst 和 cycles
/hardware-event-observe observe pid=16874 cache-misses branches
/hardware-event-observe observe pid=16874 branch-misses --samples 10 --csv-out out/node.csv --svg-out out/node.svg
```

这个 Skill 最终会委托给下面的本地脚本：

```bash
bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "trace pid=16874 inst cycles" --samples 5 --plain
```

脚本会确保调用发生在当前仓库根目录下，并使用 `python3` 配合 `PYTHONPATH=src`，这与当前工作区里已经验证过的运行方式保持一致。