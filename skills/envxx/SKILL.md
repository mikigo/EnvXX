---
name: envxx
description: |
  使用 EnvXX 管理免安装的 Python、Node.js、Go、JDK、uv、Bun 运行时，以及在 EnvXX 仓库里新增一个工具 provider。
  当用户需要运行某个版本的 Python/Node/Go/Java、抱怨机器上没有装某种运行时、想把工具下载到本地目录而不是全局安装、
  需要给项目单独准备一套运行时、或者问"这个项目怎么加一个新工具"时使用。也适用于用户提到 envxx 命令、~/.envxx 目录、
  项目级 .envxx、portable/免安装运行时、绿色版工具、多版本并存、或希望删掉一个目录就等于卸载的场景。
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
---

# EnvXX

EnvXX 把一个工具的**官方免安装版**下载到一个 store 目录，按需调用。它不管依赖，不编译源码，不维护 lockfile：只负责"这个工具本身装在哪"。删掉 store 就等于卸载。

两件事：**用它**，或者**给它加工具**。

## 判断用户要哪一半

- 要跑 python/node/go/java、机器上没有、或者要指定版本 → 看「使用」。
- 要在 EnvXX 仓库里支持一个新工具、或者改一个已有 provider → 看「扩展」，细读 `references/adding-a-provider.md`。

不确定就看仓库里有没有 `envxx/providers/`：有就是后者。

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

版本号也可以直接跟在选择器后面，管理命令放在其后：

```bash
envxx python3.12 install       # 等同 envxx python install 3.12
envxx python3.12 where         # 等同 envxx python where 3.12
envxx python3.12 list          # 版本无意义，等同 envxx python list
```

`list` 和 `search` 覆盖所有版本，所以选择器里的版本会被丢掉。

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

**默认入口不要重复写。** JDK 的默认入口是 `java`，`envxx jdk21 --version` 对，`envxx jdk21 java --version` 会把 `java` 当参数传给 java 自己，报 `ClassNotFoundException`。同理 `envxx node22 node -v` 不成立。只有非默认入口（`pip`、`npm`、`javac`、`gofmt`、`uvx`）才需要显式写。

### 装进运行时的命令

`pip install` 装到某个 Python 里的控制台脚本，可以按名字跑：

```bash
envxx python3.11 pip install black
envxx python3.11 black .
```

前提是脚本确实在 `Scripts/`（Unix 的 `bin/`）里。名字没找到不会报错，而是按普通参数交给默认入口，所以 `envxx python3.11 script.py` 行为不变。副作用：如果当前目录恰好有个同名文件或包，Python 会按自己的规则处理它（例如 `envxx python3.11 envxx` 会去找 `./envxx/`）。

### 支持的工具

运行时（可多版本并存）：`python`、`node`、`go`、`jdk`、`uv`、`bun`
应用（留最新即可）：`claude`、`opencode`、`cc-switch`、`xterm`、`wt`、`notepad--`、`marktext`、`dbeaver`、`dufs`

`xterm`、`wt`、`notepad--` 只有 Windows 版。`dbeaver` 支持 Windows 和 Linux，macOS 上会报不支持（官方只发 dmg）。`marktext` 三个平台都有。这些限制来自上游发了什么资产，不要假设它们跨平台。

`notepad--` 的 arm64 包只有部分版本附带，arm64 机器上能列的版本比 x64 少得多。`marktext` 的 v0.24 线还在 rc 阶段，会被过滤掉。

### 只下载安装包的工具

`vscode`、`7zip`、`wechat`、`wecom` 是另一类：官方只发安装程序，没有绿色版。

`envxx wechat install` **只下载，不安装**。文件落在 `downloads/`，命令会打印绝对路径，用户自己双击。不要告诉用户这几个工具"装好了"，也不要建议用 `envxx wechat` 直接运行——它们没有可运行的入口。

- `list` 显示已下载的安装包，`where` 给出文件路径。
- 没下载过时 `where` 会报错并提示先 `install`。
- 微信和企业微信的目录只有当前版本，`search` 只有一行；VS Code 和 7-Zip 能列历史。
- 这类工具不占 `tools/`，删 `downloads/` 里的文件就能清掉。

### Store 位置

优先级：`ENVXX_HOME` → 从 cwd 向上找到的项目级 `.envxx` → `~/.envxx`。

项目级由 `envxx init` 创建，含 `tools/ downloads/ cache/ .locks/` 和一个 `.project` 标记文件，并自动写进 `.gitignore`。向上查找只认带标记的目录，家目录本身不算项目级。

写命令时注意：在带 `.envxx` 的仓库里执行 `envxx`，装的东西进项目目录，不是全局。用户如果问"为什么没装到 ~/.envxx"，先看有没有项目级 store。

## 扩展：加一个工具

新增工具是填空：写一个 provider，登记进注册表，然后对着**真实的包结构**验证。`references/adding-a-provider.md` 有字段说明、平台映射、checksum 策略、测试写法和验证手法。

最短路径：

1. 读 `envxx/providers/uv_provider.py`（最简单：GitHub release，二进制在包根）和 `envxx/providers/go_provider.py`（清单自带 sha256）当模板。
2. 新建 `envxx/providers/<tool>_provider.py`，定义 `ToolSpec` 和 `Provider` 子类。
3. 在 `envxx/providers/__init__.py` 的 `_PROVIDER_TYPES` 登记，补 `__all__`。
4. 在 `tests/test_runtimes.py` 或 `tests/test_providers.py` 加用例，用假 payload，不联网。
5. 跑 `python -m pytest -q`，再做一次真实安装。

### 三条约定

**排序只在基类发生。** `_fetch_versions()` 返回什么顺序都行，`Provider.search()` 统一排成新版本在前。不要在 provider 里 `sort`。需要折叠时才覆写 `display_versions()`，用 `latest_per_line(self.search(), depth=N)`。

**先解包看一眼再写路径。** 顶层有没有目录决定 `strip_top`；二进制在 `bin/`、包根、还是 `Contents/Home/bin/`（macOS 的 JDK）决定 `entrypoints`。猜不出来。大包用 Range 读 zip 末尾的中央目录，或读 tarball 头几兆，不要下 200MB 确认。

**校验要么来自 API，要么指向校验文件。** `api_digest` 是 payload 自带 digest，`shasums_file` 是 `<hex>  <name>` 列表，`sha256_file` 是单行 hex。拿不到就写 `none`，别假装有。

## 常见坑

全是实际撞过的，按遇到概率排：

- **同名参数被当成脚本。** `envxx python3.12 install` 曾经在装完之后让 Python 去找名为 `install` 的文件。管理命令名要认得出来，见 `MANAGE_COMMANDS`。
- **默认入口重复写。** `envxx jdk21 java -version` 必然失败，见「换入口」。
- **macOS 的 JDK 是 bundle**：`Contents/Home/bin/java`，Windows/Linux 是 `bin/java`。
- **包的顶层目录不能猜。** Go 的顶层叫 `go`，bun 的叫 `bun-windows-x64`，ripgrep 12 之前还是平铺的。
- **Adoptium 版本字段不一致**：`openjdk_version` 可能四段也可能 `27+35`，用 `semver` 再剥 `+`。
- **独立版 Bun 没有 `bunx`**：只有 `bun.exe`，`bunx` 是 npm 安装时创建的。
- **Git Bash 的 `test -f foo` 对 `foo.exe` 也返回真**，`basename` 会丢扩展名。
- **`hasattr` 判断可选方法**通常说明它该在基类里。

## 排障

按报错定位环节：

**`has no <name> at <path>`**：安装成功但找不到入口。对比报错里的 path 和实际目录（`envxx <tool> list` 给路径，或直接 ls）。多数是路径写错：顶层目录名不对，或 macOS bundle 多两层。改 `entrypoint_candidates()`，不要改安装逻辑。

**`can't open file` / `MODULE_NOT_FOUND` / `ClassNotFoundException`**：参数被当成脚本或模块名了。见「默认入口不要重复写」和「同名参数被当成脚本」。注意这类错误发生在**安装成功之后**，安装日志末尾已经打印过 `installed ...`，所以不是安装失败。

**`not available for <platform>`**：远端没有当前平台的构建。筛选条件太窄（只匹配 `unknown-linux-gnu` 而项目只发 `musl`），或平台映射写错。先 `search --all` 看版本，再看资产名。

**`checksum mismatch`**：下载内容和 digest 不符。检查是不是选了 `installer` 而不是 `archive`（Go 清单两种都有），或镜像返回了错误页。

**`GitHub API rate limit`**：等配额，或设 `GITHUB_TOKEN`。分页拉目录时最容易撞上。

## 环境

- Store 默认 `~/.envxx`，优先级见上。
- 镜像变量：`ENVXX_GITHUB_MIRROR`、`ENVXX_GITHUB_API`、`ENVXX_GITHUB_RAW`、`ENVXX_NODE_DIST`、`ENVXX_CCSWITCH_MIRROR`。Go 走 `dl.google.com`，JDK 走 Adoptium API，不在镜像范围内。
- GitHub 未登录限流 60 次/小时，设 `GITHUB_TOKEN` 提到 5000。
