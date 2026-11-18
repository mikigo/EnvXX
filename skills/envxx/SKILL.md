---
name: envxx
description: |
  使用 EnvXX 管理免安装的 Python、Node.js、Go、JDK、uv、Bun 运行时，以及在 EnvXX 仓库里新增一个工具 provider。
  当用户需要运行某个版本的 Python/Node/Go/Java、抱怨机器上没有装某种运行时、想把工具下载到本地目录而不是全局安装、
  或者问"这个项目怎么加一个新工具"时使用。也适用于用户提到 envxx 命令、~/.envxx 目录、portable/免安装运行时、
  绿色版工具、多版本并存、或希望删掉一个目录就等于卸载的场景。
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
---

# EnvXX

EnvXX 把一个工具的**官方免安装版**下载到 `~/.envxx`，按需调用。它不管依赖，不编译源码，不维护 lockfile：只负责"这个工具本身装在哪"。删掉 `~/.envxx` 就等于卸载。

两件事：**用它**，或者**给它加工具**。

## 判断用户要哪一半

- 要跑 python/node/go/java、机器上没有、或者要指定版本 → 看「使用」。
- 要在 EnvXX 仓库里支持一个新工具、或者改一个已有 provider → 看「扩展」，细读 `references/adding-a-provider.md`。

不确定就看仓库里有没有 `envxx/` 包：有就是后者。

## 使用

### 基本形状

```bash
envxx python3.11 -m pip install requests   # 没有 3.11 会先下载再执行
envxx node22 -v
envxx go1.27 version
envxx claude                               # 应用类，写名字就行
```

选择器把工具名和版本连在一起写：`python3.11`、`node22`、`go1.27`、`jdk21`、`uv0.13`、`bun1.4`。别名也认：`golang1.27` 等于 `go1.27`，`java21` 和 `temurin21` 等于 `jdk21`，`nodejs22` 等于 `node22`。裸写工具名（`envxx node`）走的是子命令帮助，不会执行。

### 管理子命令

```bash
envxx <tool> search            # 远端有哪些版本
envxx <tool> search --all      # 完整历史（默认按版本线折叠）
envxx <tool> list              # 本地已下载
envxx <tool> install 3.11.9    # 只下载不运行
envxx <tool> where             # 入口的绝对路径
envxx <tool> update            # 升到最新（应用类）
envxx <tool> uninstall 3.11.18 # 应用类可简写 rm
```

列表一律**新版本在前**。`search` 对版本多的工具每行只显示最新补丁（Go 显示 `1.27.4` 而不是 1.27 线的全部）。

### 换入口

同一个工具的不同入口直接写名字：

```bash
envxx python3.11 pip install requests
envxx node22 npm run dev
envxx node22 npx create-vite
envxx go1.27 gofmt -l .
envxx uv0.13 uvx ruff check .
```

`envxx run` 是给脚本拼接用的等价写法：

```bash
envxx run python@3.11:pip --version
envxx run node@22:npm --version
```

### 装进运行时的命令也能叫

`pip install` 装到 Python 里的控制台脚本，可以直接按名字跑：

```bash
envxx python3.11 pip install -e .
envxx python3.11 envxx --help     # 找到 Scripts/envxx.exe
```

找不到的名字不会被吞掉，仍然按普通参数交给默认入口，所以 `envxx python3.11 script.py` 行为不变。

### 支持的工具

运行时（可多版本并存）：`python`、`node`、`go`、`jdk`、`uv`、`bun`
应用（留最新即可）：`claude`、`opencode`、`cc-switch`、`xterm`、`dufs`

## 扩展：加一个工具

新增工具是填空：写一个 provider，登记进注册表，然后对着**真实的包结构**验证。`references/adding-a-provider.md` 有完整的字段说明、平台映射表、checksum 策略和测试写法。开工前至少读一遍那两个 provider 模板之一。

最短路径：

1. 读 `envxx/providers/uv_provider.py`（结构最简单，Archive 二进制在根目录）和 `envxx/providers/go_provider.py`（清单自带 sha256）当模板。
2. 在 `envxx/providers/` 新建 `<tool>_provider.py`，定义 `ToolSpec` 和 `Provider` 子类。
3. 在 `envxx/providers/__init__.py` 的 `_PROVIDER_TYPES` 里登记，补 `__all__`。
4. 在 `tests/test_runtimes.py` 或 `tests/test_providers.py` 里加用例，用假的 JSON payload，不联网。
5. 跑 `python -m pytest -q` 和一次真实安装。

### 三条必须遵守的约定

**排序只在基类发生。** `_fetch_versions()` 返回什么顺序都行，`Provider.search()` 会统一排成新版本在前。不要在 provider 里再 `sort`。`display_versions()` 只在需要折叠时覆写，用 `latest_per_line(self.search(), depth=N)`。

**先解包看一眼再写路径。** 顶层有没有目录决定 `strip_top`；二进制在 `bin/`、根目录、还是 `Contents/Home/bin/`（macOS 的 JDK）决定 `entrypoints`。这些猜不出来。大包用 Range 请求读末尾的 zip 中央目录，或读 tarball 的头几兆，不要下 200MB 去确认。

**校验要么来自 API，要么指向校验文件。** `checksum="api_digest"` 表示 payload 里自带 digest；`"shasums_file"` 表示有 `<hex>  <name>` 列表；`"sha256_file"` 是单行 hex。拿不到就别假装有，写 `"none"`。

## 常见坑（都是实际撞过的）

- **macOS 的 JDK 是 bundle**：`Contents/Home/bin/java`，Windows/Linux 是 `bin/java`。
- **Adoptium 版本字段不一致**：`openjdk_version` 可能四段也可能 `27+35`，用 `semver` 再剥 `+`。
- **独立版 Bun 没有 `bunx`**：只有 `bun.exe`，`bunx` 是 npm 安装时创建的。
- **Git Bash 的 `test -f foo` 对 `foo.exe` 也返回真**，`basename` 会丢扩展名。
- **`hasattr` 判断可选方法**通常说明它该在基类里。

## 排障

报错信息能直接定位到环节，按这个顺序看：

**`has no <name> at <path>`**：安装成功但找不到入口。先看报错里给出的 path，和实际目录对比（`envxx <tool> list` 能拿到路径，或直接 `ls ~/.envxx/tools/<tool>/<version>/`）。绝大多数是路径写错了：顶层目录名不是你以为的那个，或者 macOS 的 bundle 多两层 `Contents/Home`。这时改 `entrypoint_candidates()`，不要去改安装逻辑。

**`not available for <platform>`**：远端目录里没有当前平台的构建。可能是筛选条件太窄（比如只匹配 `unknown-linux-gnu`，而项目只发了 `musl`），也可能是平台映射表写错了。先 `envxx <tool> search --all` 看有没有版本，再看资产名。

**`checksum mismatch`**：下载到的东西和声明的 digest 不一致。检查是不是选了 `installer` 而不是 `archive`（Go 的清单里两种都有），或者镜像返回了错误页面。

**`GitHub API rate limit`**：等配额恢复，或者设 `GITHUB_TOKEN`。目录分页拉取时尤其容易撞上。

## 环境

- 所有内容在 `~/.envxx`，可用 `ENVXX_HOME` 改。
- 镜像变量：`ENVXX_GITHUB_MIRROR`、`ENVXX_GITHUB_API`、`ENVXX_GITHUB_RAW`、`ENVXX_NODE_DIST`、`ENVXX_CCSWITCH_MIRROR`。Go 走 `dl.google.com`，JDK 走 Adoptium API，不在镜像范围内。
- GitHub 未登录限流 60 次/小时，设 `GITHUB_TOKEN` 提到 5000。
