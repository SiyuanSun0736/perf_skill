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
- 支持首次自动 clone Brendan Gregg 的 FlameGraph 仓库，并把录制得到的 `.data` 渲染成火焰图 SVG
- 支持在解析 `.data` 后继续自动跑 `perf report --stdio` 与 `perf annotate --stdio`
- 支持用 `exercise` 子命令启动 `stress-ng` 或 `ab`，并在压测期间自动观测目标进程或压测进程本身
- 支持用 Python 在采样结束后自动生成摘要，补充趋势、miss rate、专家诊断和 perf.data 热点汇总
- 支持把这些摘要导出成 JSON，方便自动化或后处理
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

如果 statement 里明确提到了“火焰图”，或者你显式传了 `--flamegraph-out`，CLI 还会自动切到 `perf record -g`，并在首次使用时把 `https://github.com/brendangregg/FlameGraph.git` clone 到当前 `PERF_SKILL_HOME` 下，默认会落到 `~/.openclaw/perf-skill/FlameGraph`，如果 skill 是从 `~/.ironclaw/skills` 或 `~/.zeroclaw/skills` 启动，则会跟随对应 toolkit home，最后输出火焰图 SVG：

```bash
perf-skill observe "追踪 node 的 cycles 并生成火焰图" --seconds 10
perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data --flamegraph-out out/node-flamegraph.svg
```

如果你要解析已有的 `.data` 文件，也可以直接走 `perf script` 代理：

```bash
perf-skill observe "解析 out/node_targetpid4242_cycles_data_20260519T120000.data"
perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data
```

如果你想在 `.data` 的 Python summary 之后继续做“二跳分析”，现在可以直接追加 `perf report --stdio` 或针对最热符号自动跑 `perf annotate --stdio`：

```bash
perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data --summary --report-stdio
perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data --annotate-top
perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data --annotate-symbol 'v8::Function+0x10'
```

如果你想用 Python 做一些原生一行 `perf` 很难直接给出的分析，可以打开 summary 层。它会在采样结束后给出均值、峰值、趋势，以及 branch miss rate、cache miss rate 这类派生指标；同时还会自动标出 IPC 突降、miss rate 突增这类异常时间点，并补充更接近“专家经验”的结论和下一步建议。解析 `.data` 时则会额外汇总 top event、top thread、top callchain、top comm、top symbol，并给出按占比排序的热点：

```bash
perf-skill observe "trace pid=4242 inst cycles" --summary
perf-skill observe "trace pid=4242 branches branch-misses" --summary-out out/summary.json
perf-skill observe "解析 out/node_targetpid4242_cycles_data_20260519T120000.data" --summary
```

live observe 的异常点会在 summary 里以对应采样时间输出；现在会追加 `insight` 和 `next-step` 这几类行，把技术诊断和后续动作明确下来，而且 plain/dashboard 实时输出也会在异常发生时直接标出来。若要给新手做术语通俗化，应由 skill/AI 在回答时完成，而不是依赖 CLI summary 自己输出隐喻。`.data` 解析时的线程聚合会以 `top-thread` 形式展示，键格式是 `comm pid/tid`，带缩进行调用栈块的 `perf script` 输出会进一步汇总成 `top-callchain` 热点，并额外输出 `hotspot` 行帮助你快速决定接下来要不要跑 `perf annotate`。

如果你想把“压测 + perf 观测”收成一条命令，现在可以用 `exercise`。它会先启动 `stress-ng` 或 `ab`，然后在压测期间 attach 到目标进程；如果你没有显式指定目标，它就默认观察压测进程本身，并在结束后把压测输出和 perf summary 一起打印出来：

```bash
perf-skill exercise stress-ng --load-args "--cpu 4 --timeout 10" --summary
perf-skill exercise ab "trace comm=nginx cache-misses" --load-args "-n 1000 -c 50 http://127.0.0.1:8080/" --summary
```

`exercise` 目前更适合“压测 + live perf stat”。如果你的目标是热点、符号、火焰图、整机观测、page-fault 排名，或者先做发现再决定 attach 哪个进程，不要硬把整条工作流塞给 Python CLI；更合适的是先用 `pgrep`、`ps`、`free`、`vmstat`、`smem` 或原生 `perf` 做发现，再把明确的目标或 `.data` 交回 `perf-skill` 继续总结和渲染。

## AI/Agent 路由速查

下面这张表说的是“AI 应该怎么编排工作流”，不是“解析器必须一条 statement 直接吃下”。能走 `perf-skill` 就走；超出它当前边界时，优先用 shell 和原生 `perf` 补上前后半程。

| 用户意图 | 首选路径 | 不要硬塞给 Python 的部分 |
| --- | --- | --- |
| 已知目标，只看 counters、IPC、summary | `perf-skill observe` | 无 |
| 已知目标，压测期间只看 counters | `perf-skill exercise` | `stress-ng`/`ab` 参数决策由 AI 做 |
| 要热点、符号、调用栈、火焰图、热点图片 | `perf record -g` + `perf-skill observe --data-in` | 录制和多步编排优先交给 shell + 原生 `perf` |
| 要看整机 branch、cache、page-fault | 原生 `perf ... -a` | system-wide 发现不要伪装成单 PID attach |
| 想先找 page-fault 最多的程序 | 原生 `perf record -a` 或 `perf stat -a`，再回到 `perf-skill` 总结 | offender discovery |
| 只说“内存占用高”，没给 target | 先 `free`/`vmstat`/`ps`/`smem`，再决定 `perf stat` 或 `perf record -g` | baseline 和 target discovery |
| 同名进程有多个 PID | 先 `pgrep -ax` 或 `ps -C` 列出来，再问用户选哪一个 | PID 歧义处理 |

## 场景化工作流

下面这些场景是给人和 agent 共用的操作范式。它们强调的是“怎么编排整条链路”，不是要求所有步骤都只能通过声明式 parser 完成。

1. `我要给 cpu50 的压力，然后探测 node 的 branch 10s，告诉我结果`

  这是“压测 + 已知进程 + summary counters”场景。先解析 `node` 对应的 PID；如果只有一个，就直接用 `exercise`，让 CLI 负责 live `perf stat` 和 summary。

  ```bash
  pgrep -x node
  perf-skill exercise stress-ng "trace pid=4242 branches branch-misses" \
    --load-args "--cpu 1 --cpu-load 50 --timeout 10" \
    --seconds 10 --summary
  ```

2. `我要给 cpu50 的压力，然后探测 node 的 branch 10s，并告诉我热点信息/符号表`

  这是“压测 + 已知进程 + 热点/符号”场景，应该切到 `perf record -g`。`exercise` 负责不了这条链，所以更合适的做法是让 shell 起压测，再用原生 `perf` 录制，最后交给 `perf-skill` 做 summary、`perf report --stdio` 或 `perf annotate`。

  ```bash
  pgrep -x node
  stress-ng --cpu 1 --cpu-load 50 --timeout 12 &
  perf record -g -o out/node-branches.data -e branches,branch-misses -p 4242 -- sleep 10
  perf-skill observe --data-in out/node-branches.data --summary --report-stdio
  perf-skill observe --data-in out/node-branches.data --annotate-top
  ```

3. `我要给 cpu50 的压力，然后探测 node 的 branch 10s，给我生成图片`

  先判断用户到底要“趋势图”还是“热点图”。如果是 branch 计数趋势，直接导出 SVG timeline；如果是热点图片，录制 `.data` 后生成 FlameGraph。

  ```bash
  pgrep -x node
  perf-skill exercise stress-ng "trace pid=4242 branches branch-misses" \
    --load-args "--cpu 1 --cpu-load 50 --timeout 10" \
    --seconds 10 --svg-out out/node-branches.svg

  stress-ng --cpu 1 --cpu-load 50 --timeout 12 &
  perf record -g -o out/node-branches.data -e branches,branch-misses -p 4242 -- sleep 10
  perf-skill observe --data-in out/node-branches.data --flamegraph-out out/node-branches-flamegraph.svg
  ```

4. `我要给 cpu50 的压力，探测整个电脑的 branch 10s`

  这是整机观测，不该先去猜哪个 PID。直接用 system-wide `perf -a`，必要时再从整机结果里继续缩小到单进程。

  ```bash
  stress-ng --cpu 1 --cpu-load 50 --timeout 12 &
  perf stat -a -e branches,branch-misses -- sleep 10
  ```

5. `我要寻找 page_fault 最多的程序`

  这是 offender discovery。先做一次 system-wide 的短录制，再用 `perf-skill` summary 看 `top-comm`、`top-thread` 和热点，确认真正值得跟进的对象。

  ```bash
  perf record -a -g -o out/pagefaults.data -e page-faults -- sleep 10
  perf-skill observe --data-in out/pagefaults.data --summary
  ```

6. `我的内存占用一直很高，我应该怎么测试`

  先做 baseline，再决定是不是 perf 的活。先区分是全局内存紧张、swap 抖动、page-fault 压力，还是单个进程 RSS 太大；目标清楚以后，再决定要 `perf stat` 还是 `perf record -g`。

  ```bash
  free -h
  vmstat 1 5
  ps -eo pid,comm,rss,%mem --sort=-rss | head
  smem -rk | head
  perf stat -p 4242 -e page-faults,minor-faults,major-faults -- sleep 10
  ```

7. `我说的是 node，但机器上有多个 node 进程`

  不要让 CLI 直接报歧义错误，也不要默认挑一个 PID。先把候选 PID 和命令行列出来，再让用户选一个。

  ```bash
  pgrep -ax node
  ps -C node -o pid,cmd
  ```

8. `我已经有 perf.data 了，继续告诉我热点/火焰图/符号表`

  这是 `.data` 二跳分析，最适合交给 `perf-skill observe --data-in`。此时不必再重新 attach；直接复用现成数据做 summary、`perf report --stdio`、`perf annotate` 或火焰图。

  ```bash
  perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data --summary --report-stdio
  perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data --annotate-top
  perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data --flamegraph-out out/node-flamegraph.svg
  ```

9. `服务器有点卡，但我还不知道该盯哪个进程`

  这是 target discovery。先看 CPU、内存和监听进程，再决定 attach 对象。只有当目标已经明确时，才值得进入 `observe` 或 `record -g`。

  ```bash
  ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head
  ps -eo pid,comm,rss,%mem --sort=-rss | head
  ss -lntp | head
  perf-skill events branch
  ```

## 最短操作清单

下面这组命令是值班时最常复制的最小集合。先把 `4242` 换成目标 PID；如果目标还不清楚，就先跑前面的发现命令，不要急着 attach。

```bash
# 1) 先确认目标 PID
pgrep -ax node
ps -C node -o pid,cmd

# 2) 已知 PID，看 counters / IPC / summary
perf-skill observe "trace pid=4242 inst cycles branches branch-misses" --seconds 10 --summary

# 3) 压测期间看 live counters
perf-skill exercise stress-ng "trace pid=4242 branches branch-misses" \
  --load-args "--cpu 1 --cpu-load 50 --timeout 10" \
  --seconds 10 --summary

# 4) 要热点 / 符号 / 调用栈
perf record -g -o out/target.data -e cycles -p 4242 -- sleep 10
perf-skill observe --data-in out/target.data --summary --report-stdio
perf-skill observe --data-in out/target.data --annotate-top

# 5) 要火焰图
perf-skill observe --data-in out/target.data --flamegraph-out out/target-flamegraph.svg

# 6) 整机看 branch
perf stat -a -e branches,branch-misses -- sleep 10

# 7) 找 page-fault 最多的程序
perf record -a -g -o out/pagefaults.data -e page-faults -- sleep 10
perf-skill observe --data-in out/pagefaults.data --summary

# 8) 内存先做 baseline
free -h
vmstat 1 5
ps -eo pid,comm,rss,%mem --sort=-rss | head
```

现在 `top-callchain` 还会继续细分成按事件分组的 `top-callchain[events]`，例如把 `cycles` 的热点链和 `sched:sched_switch` 的热点链分开看。实时 dashboard 里也会保留一个异常摘要，显示累计异常数、最近时间窗内异常数，以及最近一次异常时间，避免长跑时旧 alerts 被滚动淹没。

如果只是想先看当前机器支持哪些事件，可以直接走 `perf list`：

```bash
perf-skill events
perf-skill events cache
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
perf-skill exercise --help
```

## 支持的声明式语句

当前解析器是刻意做成“窄而稳定”的，不追求任意自然语言都能猜中。上面的“AI/Agent 路由速查”和“场景化工作流”可以更宽，但那是工作流编排能力，不等于 parser 会把每一句自然语言都直接吃成单条 CLI 命令。

支持的形式包括：

- `trace comm=python pid=4242 inst cycles`
- `observe python 4242 instructions`
- `observe node instructions`
- `observe node cpu-clock sched:sched_switch`
- `追踪 node 的 cycles 并输出 perf.data`
- `追踪 node 的 cycles 并生成火焰图`
- `解析 out/node_targetpid4242_cycles_data_20260519T120000.data`
- `解析 out/node_targetpid4242_cycles_data_20260519T120000.data 并生成火焰图`
- `trace pid=4242 inst cycles summary`
- `trace pid=4242 inst cycles for 5 seconds`
- `observe pid=4242 cache-misses 10 samples`
- `追踪 comm=nginx pid=31337 inst cycles`
- `追踪 node 的 指令 和 周期`
- `我要追踪node20秒内的cycles`
- `探测20秒node的cycles并生成图像`
- `生成10s内node的branchs的图像`
- `追踪 pid=31337 的 inst 和 cycles，采样10次`
- `追踪 node 持续 30 秒，采 20 个样本`
- `watch pid 9001 events=inst,cycles,cache-misses`

事件列表现在刻意走显式子命令。请优先使用 `perf-skill events`、`perf-skill events cache`，或者由 skill 把自然语言的“列出事件”请求路由到这个子命令，而不是继续扩 parser。

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

如果你还想把 Python 生成的摘要写成 JSON，可以用：

```bash
perf-skill observe "trace pid=4242 inst cycles" --summary-out out/summary.json
perf-skill observe --data-in out/python_targetpid4242_cycles_data_20260519T120000.data --summary-out out/data-summary.json
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

推送类似 `v1.0.1` 这样的 tag 时，workflow 会执行：

- 构建 wheel 和 sdist
- 校验 tag 与 `perf_skill.__version__` 是否一致
- 根据上一个 tag 到当前 tag 的提交区间生成 changelog
- 上传构建产物
- 创建 GitHub Release 并附带构建产物

现在这条流程支持一条先 TestPyPI、后 PyPI 的两阶段发布路径：

- 先推 `test-v1.0.1`，把构建产物发布到 TestPyPI，创建 GitHub 预发布，并从 TestPyPI 做一次 smoke install。
- 确认这一步通过后，再在同一个提交上推 `v1.0.1`，创建正式 GitHub Release，发布到 PyPI，并从 PyPI 再做一次 smoke install。

当前发布流程使用两个辅助脚本：

- `scripts/release/validate_tag.py`：校验 `vX.Y.Z` 与包版本一致
- `scripts/release/generate_changelog.py`：根据 tag 区间生成 release notes

如果你想在打 tag 之前批量更新仓库里的当前版本引用，可以直接运行：

```bash
python3 scripts/release/bump_version.py 0.6.0 --dry-run
python3 scripts/release/bump_version.py 0.6.0
```

如果你要启用这条两阶段发布链，需要分别在 TestPyPI 和 PyPI 上把这个仓库配置成 trusted publisher。配置完成后，`test-vX.Y.Z` 会先走 TestPyPI 预发布验证，`vX.Y.Z` 再走正式 PyPI 发布；同时 skill 自带的 `.github/skills/hardware-event-observe/package-requirement.txt` 会把无源码场景下的运行时安装固定到正式 release 对应的 PyPI 版本。

也可以本地手动运行这两个发布脚本：

```bash
PYTHONPATH=src python3 scripts/release/validate_tag.py v1.0.1
PYTHONPATH=src python3 scripts/release/generate_changelog.py --tag v1.0.1 --output /tmp/release-notes.md
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

如果你要把这份 skill 安装到另一台 Linux 机器上并实际跑起来，优先看 [docs/guide.md](docs/guide.md)。如果你要把它放进 ZeroClaw、IronClaw 或 openclaw 的 skills 目录，先看 [docs/claw-toolkits.md](docs/claw-toolkits.md)。如果你只关心 Ironclaw 的交互命令，可以直接看 [docs/ironclaw.md](docs/ironclaw.md)。

当前仓库同时保留了两份同内容的 skill 目录：`skills/hardware-event-observe/` 给 claw 安装命令直接从仓库根扫描时使用，`.github/skills/hardware-event-observe/` 给 VS Code / Copilot Skill 发现机制使用。

这个仓库还带了一份 Copilot Skill，位置在：

```text
.github/skills/hardware-event-observe/
```

这样你可以直接在 VS Code Chat 里用自然语言触发本地 CLI。

示例：

```text
/hardware-event-observe 追踪 comm=node pid=16874 的 inst 和 cycles
/hardware-event-observe observe pid=16874 cache-misses branches
/hardware-event-observe 解析 out/node_targetpid16874_cycles_data_20260519T120000.data 并生成火焰图
/hardware-event-observe observe pid=16874 branch-misses --samples 10 --csv-out out/node.csv --svg-out out/node.svg
```

这个 Skill 最终会委托给下面的本地脚本：

```bash
bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "trace pid=16874 inst cycles" --samples 5 --plain
```

如果脚本能直接看到当前仓库源码，它会以 editable 模式安装这份本地源码，因此仓库里的后续代码修改会直接生效。如果 skill 被安装到当前项目的 `./skills/` 下，它会默认把运行时放到当前项目里的 `./.openclaw/perf-skill/venv`；如果 skill 被安装到全局 `~/.openclaw/skills/`、`~/.ironclaw/skills/` 或 `~/.zeroclaw/skills/` 下，它会默认把运行时放到对应 toolkit home 里的 `perf-skill/venv`。当本地仓库源码不可见时，脚本会改从 skill 自带的 PyPI requirement 安装对应版本的 Python 包；需要覆盖时，可以设置 `PERF_SKILL_PACKAGE_SOURCE`。生成火焰图时，还会在当前 `PERF_SKILL_HOME` 下自动 clone Brendan Gregg 的 FlameGraph 仓库。若要统一改安装位置，可以设置 `OPENCLAW_HOME`、`IRONCLAW_HOME`、`ZEROCLAW_HOME` 或 `PERF_SKILL_HOME`；如果只想单独改 Python 环境或 FlameGraph 仓库位置，可以分别设置 `PERF_SKILL_VENV_DIR` 和 `PERF_SKILL_FLAMEGRAPH_DIR`。