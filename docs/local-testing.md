# 本地测试说明

本文档说明如何在本地验证 perf-skill 的核心功能，包括解析、分组、真实采样、导出、发布脚本和本地打包。

## 适用环境

- Linux 环境
- `python3` 可用
- 系统已安装 `perf`
- 最好有一个可持续运行一小段时间的目标进程，例如 `node`、`python` 或你自己的业务进程

如果你当前环境里的系统 Python 没有直接提供 `pip`，建议优先使用虚拟环境，不要直接往系统 Python 里安装依赖。

## 进入仓库

```bash
cd /path/to/perf_skill
```

下文示例默认你已经位于仓库根目录。

## 方式一：不安装，直接从源码运行

仓库里的大多数本地验证命令都可以直接使用源码路径运行：

```bash
PYTHONPATH=src python3 -m perf_skill --help
```

这种方式最适合开发中快速验证改动。

但如果你要验证 `--svg-out`，建议优先在虚拟环境中安装项目依赖，因为 SVG 图现在由 matplotlib 渲染。

## 方式二：安装到虚拟环境后测试

如果你想模拟更接近最终用户的安装方式，可以先创建虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

安装完成后，可以直接使用：

```bash
perf-skill --help
```

## 1. 运行单元测试

先跑完整单测，确认基础逻辑没有被改坏：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

当前测试覆盖了这些模块：

- 解析器
- perf 命令构造与 group 规划
- 失败 group 的局部拆分重试
- CSV 和 SVG 导出
- release 工具脚本

## 2. 验证 CLI 帮助输出

确认主命令和子命令的帮助信息可用：

```bash
PYTHONPATH=src python3 -m perf_skill --help
PYTHONPATH=src python3 -m perf_skill observe --help
```

建议重点看这些内容是否存在：

- `--version`
- `--group-mode`
- `--pmu-slots`
- `--no-group-retry`
- `--csv-out`
- `--svg-out`
- `--no-svg-legend`

## 3. 先做 dry-run 验证

真正附着进程之前，先确认声明式语句解析结果、事件补齐、自动分组和最终 perf 命令是否符合预期。

如果本机有长期运行的 `node` 进程，可以直接这样测：

```bash
pid=$(pgrep -xo node)
PYTHONPATH=src python3 -m perf_skill observe "trace pid=$pid branch-misses cache-misses" --dry-run --pmu-slots 2
```

重点检查输出中的这些字段：

- `events`
- `groups`
- `fallbacks`
- `command`

如果你的目标不是 `node`，可以把 `pid=$(pgrep -xo node)` 替换成自己的目标 PID。

## 4. 做一次真实采样

确认真正运行 `perf stat` 时，能够采到样本并输出 IPC。

```bash
pid=$(pgrep -xo node)
PYTHONPATH=src python3 -m perf_skill observe "trace pid=$pid branch-misses cache-misses" --samples 1 --plain
```

正常情况下你应该能看到一行类似下面的输出：

```text
[08:00:01] pid=16874 comm=node instructions=491.97K cycles=3.43M ... ipc=0.14
```

如果出现权限问题或 `<not counted>`，优先检查：

- 当前内核是否支持对应 PMU 计数器
- `perf_event_paranoid` 是否过高
- 当前环境是否是容器、虚拟机或 WSL，并限制了硬件事件

## 5. 验证失败 group 局部拆分重试

这个特性主要通过单测覆盖，但你可以先用 dry-run 理解它会如何工作：

```bash
pid=$(pgrep -xo node)
PYTHONPATH=src python3 -m perf_skill observe "trace pid=$pid branch-misses cache-misses" --dry-run --pmu-slots 2
```

当前实现的目标是：

- 初始按 group 运行
- 某个 group 失败时，只拆这个失败 group
- 已成功的 group 保持不变
- 最后必要时再回退到更小粒度

这部分最可靠的回归方式仍然是：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## 6. 验证 CSV 和 SVG 导出

运行一个短采样，并同时导出 CSV 和 SVG：

```bash
rm -rf out
mkdir -p out
pid=$(pgrep -xo node)
PYTHONPATH=src python3 -m perf_skill observe "trace pid=$pid branch-misses cache-misses" \
  --samples 2 \
  --plain \
  --csv-out out/node.csv \
  --svg-out out/node.svg
```

检查文件是否生成：

```bash
wc -l out/node.csv
test -s out/node.svg && echo SVG_OK
```

如果你想验证“无图例 SVG”，可以再跑一遍：

```bash
pid=$(pgrep -xo node)
PYTHONPATH=src python3 -m perf_skill observe "trace pid=$pid branch-misses cache-misses" \
  --samples 2 \
  --plain \
  --svg-out out/node-no-legend.svg \
  --no-svg-legend
```

## 7. 验证 release 辅助脚本

校验 tag 和版本号是否一致：

```bash
PYTHONPATH=src python3 scripts/release/validate_tag.py v0.5.0
```

生成 changelog：

```bash
git tag -f v0.5.0 >/dev/null 2>&1
PYTHONPATH=src python3 scripts/release/generate_changelog.py --tag v0.5.0 --output /tmp/perf-skill-release-notes.md
sed -n '1,40p' /tmp/perf-skill-release-notes.md
git tag -d v0.5.0 >/dev/null 2>&1
```

## 8. 验证本地打包

如果要确认项目确实可以打成 wheel 和 sdist，建议使用单独的构建虚拟环境：

```bash
rm -rf .venv-build dist build
python3 -m venv .venv-build
.venv-build/bin/python -m pip install --upgrade pip build wheel
.venv-build/bin/python -m build
ls -1 dist
```

正常情况下会看到类似下面两个产物：

- `perf_skill-0.5.0.tar.gz`
- `perf_skill-0.5.0-py3-none-any.whl`

测试结束后可以清理：

```bash
rm -rf .venv-build dist build out /tmp/perf-skill-release-notes.md
```

## 9. 验证 GitHub Release 工作流配置

如果你只是想快速确认发布配置文件是否存在，可以直接看：

```bash
sed -n '1,240p' .github/workflows/release.yml
```

重点确认这些步骤是否存在：

- 构建 `python -m build`
- 版本校验 `scripts/release/validate_tag.py`
- changelog 生成 `scripts/release/generate_changelog.py`
- GitHub Release 上传
- 可选的 PyPI 发布 job

## 10. 常用回归命令清单

如果你只想快速回归最核心功能，可以按这个顺序跑：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
pid=$(pgrep -xo node)
PYTHONPATH=src python3 -m perf_skill observe "trace pid=$pid branch-misses cache-misses" --dry-run --pmu-slots 2
PYTHONPATH=src python3 -m perf_skill observe "trace pid=$pid branch-misses cache-misses" --samples 1 --plain
```

## 11. 常见问题

### 系统 Python 没有 pip

如果你看到：

```text
/usr/bin/python3: No module named pip
```

优先使用虚拟环境：

```bash
python3 -m venv .venv-build
.venv-build/bin/python -m pip install --upgrade pip build wheel
```

### zsh 自动更正 `pip`

如果 zsh 弹出类似：

```text
zsh: correct 'pip' to '_pip' [nyae]?
```

不要继续用当前命令链，改成显式路径调用，例如：

```bash
.venv-build/bin/python -m pip install --upgrade pip build wheel
```

### WSL 或虚拟机里硬件事件不可用

如果 perf 能列出事件但一直是 `<not counted>`，通常不是 CLI 逻辑问题，而是宿主环境没有正确暴露 PMU 计数器。