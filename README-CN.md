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
- 在需要时切换到 `perf record`，并输出自动重命名的 `.data` 文件
- 支持对已有 `.data` 文件执行 `perf script -i` 解析
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

第一次使用建议先跑 `--dry-run`，先看解析结果和生成的 `perf` 命令，再决定是否真正附着到目标进程。这里的 dry-run 是 `perf-skill` 自己做的模拟预览，原生 `perf` 并没有 `--dry-run` 选项。

```bash
perf-skill observe "trace python 4242 inst" --dry-run
```

默认情况下，CLI 会使用 `--group-mode auto` 生成 `perf stat -e` 的事件分组，例如：

- `{instructions,cycles,cache-misses}`
- `{instructions,cycles},{branches,branch-misses}`

这样能尽量把相关计数器放在同一个 perf group 中，而不是把所有事件都硬塞进一个过大的集合。

如果你想按固定样本数或固定时长停止采样，可以用：

```bash
perf-skill observe "trace pid=4242 inst cycles" --samples 10 --plain
perf-skill observe "trace pid=4242 inst cycles" --seconds 5 --plain
```

statement 里也支持更自然一点的写法，比如 `for 5 seconds`、`10 samples`、`10秒`、`采样10次`、`持续 30 秒`、`采 20 个样本`。

如果 statement 里明确说了“生成图像/图表”，CLI 还会自动打开 SVG 导出，并在你没传 `--svg-out` 时默认写到 `out/*.svg`，例如：

```bash
perf-skill observe "探测20秒node的cycles并生成图像"
perf-skill observe "生成10s内node的branchs的图像"
```

如果 statement 里提到了 `perf.data`，CLI 会自动切到 `perf record`，并在你没有显式传 `--data-out` 时，默认生成类似下面这种名字：

`out/node_targetpid4242_cycles_data_20260519T120000.data`

例如：

```bash
perf-skill observe "追踪 node 的 cycles 并输出 perf.data" --seconds 10
```

如果你要解析已有的 `.data` 文件，也可以直接走 `perf script` 代理：

```bash
perf-skill observe "解析 out/node_targetpid4242_cycles_data_20260519T120000.data"
perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data
```

如果只是想先看当前机器支持哪些事件，可以直接走 `perf list`：

```bash
perf-skill events
perf-skill events cache
perf-skill observe "查看 cache 相关事件"
```

如果你想关闭分组，可以用：

```bash
perf-skill observe "trace pid=4242 inst cycles" --group-mode off
```

如果你想强制按固定大小切组，可以用：

```bash
perf-skill observe "trace pid=4242 inst cycles branches cache-misses" --group-mode always
```

`--pmu-slots auto` 现在默认按 `4` 个硬件 slot 做自动分组。cache 和 branch 家族事件会尽量保持在一起，而像 `cpu-clock` 这类 soft event 和 `sched:sched_switch` 这类 tracepoint 不会占用这 4 个硬件 slot。也可以手动覆盖：

```bash
perf-skill observe "trace pid=4242 inst cycles" --pmu-slots 4
```

解析器现在也支持你在自然语言里直接写这些事件名，例如：

```bash
perf-skill observe "trace node cpu-clock sched:sched_switch" --plain
perf-skill observe "追踪 node 的 cpu-clock 和 sched:sched_switch" --plain
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
- `observe node instructions`
- `observe node cpu-clock sched:sched_switch`
- `追踪 node 的 cycles 并输出 perf.data`
- `解析 out/node_targetpid4242_cycles_data_20260519T120000.data`
- `trace pid=4242 inst cycles for 5 seconds`
- `observe pid=4242 cache-misses 10 samples`
- `追踪 comm=nginx pid=31337 inst cycles`
- `追踪 node 的 指令 和 周期`
- `我要追踪node20秒内的cycles`
- `探测20秒node的cycles并生成图像`
- `生成10s内node的branchs的图像`
- `追踪 pid=31337 的 inst 和 cycles，采样10次`
- `追踪 node 持续 30 秒，采 20 个样本`
- `列出 branch 相关事件`
- `支持哪些 PMU 事件`
- `查看 cache 相关事件`
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
- 如果多个事件有明显相同的前缀、后缀或 namespace，auto 模式会优先把它们放在一起
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

如果你想直接录制并输出重命名后的 `.data` 文件，可以用：

```bash
perf-skill observe "trace pid=4242 inst cycles" --data-out out/python_targetpid4242_cycles_data_20260519T120000.data --seconds 10
```

如果你要解析已经录好的 `.data` 文件，可以用：

```bash
perf-skill observe --data-in out/python_targetpid4242_cycles_data_20260519T120000.data
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

推送类似 `v0.5.1` 这样的 tag 时，workflow 会执行：

- 构建 wheel 和 sdist
- 校验 tag 与 `perf_skill.__version__` 是否一致
- 根据上一个 tag 到当前 tag 的提交区间生成 changelog
- 上传构建产物
- 创建 GitHub Release 并附带构建产物

当前发布流程使用两个辅助脚本：

- `scripts/release/validate_tag.py`：校验 `vX.Y.Z` 与包版本一致
- `scripts/release/generate_changelog.py`：根据 tag 区间生成 release notes

如果你想在打 tag 之前批量更新仓库里的当前版本引用，可以直接运行：

```bash
python3 scripts/release/bump_version.py 0.6.0 --dry-run
python3 scripts/release/bump_version.py 0.6.0
```

如果你想开启 PyPI 发布，需要先在 PyPI 上把这个仓库配置成 trusted publisher，并设置仓库变量：

```text
PUBLISH_PYPI=true
```

配置完成后，tag 构建会在 GitHub Release 之后继续把相同的 `dist/` 产物发布到 PyPI。

也可以本地手动运行这两个发布脚本：

```bash
PYTHONPATH=src python3 scripts/release/validate_tag.py v0.5.1
PYTHONPATH=src python3 scripts/release/generate_changelog.py --tag v0.5.1 --output /tmp/release-notes.md
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

脚本会确保调用发生在当前仓库根目录下，并在首次运行时自动把运行环境安装到 `~/.openclaw/perf-skill/venv`。它会以 editable 模式安装当前仓库和所需 Python 依赖，因此仓库里的后续代码修改会直接生效。如果你需要统一改安装位置，可以设置 `OPENCLAW_HOME`、`PERF_SKILL_HOME` 或 `PERF_SKILL_VENV_DIR`。