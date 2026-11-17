# EnvXX

我习惯让电脑保持干净。除了系统自带的东西，能不装就不装。要用 Python，就解压一个免安装版；要用 Node，也一样。没有安装向导，没有注册表垃圾，也没见过卸载后还剩 300MB 的目录。

这套习惯有个代价：换一台电脑，一切从头来。翻下载页、认准架构、解压、配 PATH，一个个弄。我换过几次机器，每次都在做同样的事，索性写成工具。

EnvXX 只干一件事：把官方发布的绿色版下到 `~/.envxx`，然后按需调用。想清干净，删掉这个目录就够了。

```bash
envxx python3.11 -m pip install requests
envxx node22 -v
envxx go1.27 version
envxx claude
```

## 安装 EnvXX 自己

从 [Releases](https://github.com/mikigo/EnvXX/releases/latest) 下载对应平台的 zip，解压后是一个同名目录，里面就是单文件二进制，不用装 Python：

| 系统 | 压缩包 | 解压后 |
| --- | --- | --- |
| Windows x64 | `<版本>-windows-x64.zip` | `<版本>-windows-x64/envxx.exe` |
| Windows arm64 | `<版本>-windows-arm64.zip` | `<版本>-windows-arm64/envxx.exe` |
| Linux x64 | `<版本>-linux-x64.zip` | `<版本>-linux-x64/envxx` |
| Linux arm64 | `<版本>-linux-arm64.zip` | `<版本>-linux-arm64/envxx` |
| macOS Apple Silicon | `<版本>-macos-arm64.zip` | `<版本>-macos-arm64/envxx` |
| macOS Intel | `<版本>-macos-x64.zip` | `<版本>-macos-x64/envxx` |

## 现在支持

| 工具 | 版本写法 | 入口 | 来源 |
| --- | --- | --- | --- |
| Python | `python3.11`、`python3.11.9` | `python`、`pip` | python-build-standalone |
| Node.js | `node22`、`node22.14.0` | `node`、`npm`、`npx` | nodejs.org LTS |
| Go | `go1.27`、`go1.27.4` | `go`、`gofmt` | go.dev |
| JDK | `jdk21`、`java21` | `java`、`javac`、`jar` | Adoptium 的 Temurin |
| uv | `uv0.13`、`uv0.13.8` | `uv`、`uvx` | GitHub Release 压缩包 |
| Bun | `bun1.4`、`bun1.4.4` | `bun` | GitHub Release 压缩包 |
| Claude Code | `claude` | `claude` | Open VSX 上的 VSIX |
| opencode | `opencode` | `opencode` | GitHub Release 压缩包 |
| CC Switch | `cc-switch` | `cc-switch` | GitHub Release 便携版 |
| MobaXterm | `xterm` | `xterm` | mobatek.net 便携版 |
| dufs | `dufs` | `dufs` | GitHub Release 压缩包 |

Python、Node、Go、JDK、uv、Bun 属于运行时，多个版本可以并存：`python3.11` 和 `python3.12` 各占一个目录，互不干扰。后面几个是应用，留最新版就够。

JDK 只列 17 以上的 LTS 线加上最新的特性版本，Adoptium 还在发的 Java 8、11 不会出现在 `search` 里；`jdk` 的默认版本是最新的那个，要 LTS 就写 `jdk21`。macOS 上的包是 bundle 布局，入口在 `Contents/Home/bin/java`，EnvXX 自己会找对位置。Go 的发布候选会标成 prerelease，`install` 不带版本号时不会挑到它们。

版本多的运行时（Go、JDK、uv、Bun、Node）默认每个版本线只显示最新一个补丁版，比如 Go 显示 `1.27.4` 而不是 1.27 线的全部；`search --all` 才是完整列表。

加新工具不用动命令行解析。写一个 provider，登记进注册表就行。ripgrep、fd、fzf 这些单文件工具都在候选名单里，只是我还没用到。

## 命令

```bash
envxx <tool> search            # 看远端有哪些版本
envxx <tool> search --all      # 看完整版本历史
envxx <tool> list              # 看本地已经下了哪些
envxx <tool> install 3.11.9    # 只下载不运行
envxx <tool> update            # 升到最新（应用类）
envxx <tool> where             # 打印入口的绝对路径
envxx <tool> uninstall 3.11.18 # 删除某个版本（应用类可简写 rm）
```

`search` 默认只列近期版本：应用的列表取最新 10 条，多出来的会提示用 `--all`。所有列表（`search`、`search --all`、`list`）都是新版本在前。`--all` 到底有多全取决于工具——opencode 会去翻完整的 tag 历史，其余几个本来就是全量。

`envxx python3.11` 这种写法，本地没有 3.11 时会自动拉最新补丁版再执行，不用先 install。

想直接跑应用，写名字就行：`envxx claude`。带上参数也一样：`envxx node -v` 会真的调用 node。裸的 `envxx node` 走的是子命令帮助，不会去执行。

要给同一个工具指定别的入口，直接写入口名就行。Python 带 `pip`，Node 带 `npm`、`npx`，Go 带 `gofmt`，uv 带 `uvx`：

```bash
envxx python3.11 pip install requests
envxx node22 npm run dev
envxx node22 npx create-vite
envxx go1.27 gofmt -l .
envxx uv0.13 uvx ruff check .
```

用 pip 往这个 Python 里装的东西，也能按名字直接跑。它会去 `Scripts/`（Unix 上是 `bin/`）里找同名脚本：

```bash
envxx python3.11 pip install -e .
envxx python3.11 envxx --help
envxx python3.11 black .
```

## 几个说明

所有东西都在 `~/.envxx`：

```
~/.envxx/
├── tools/        每个工具按版本一个目录
├── downloads/    下载缓存，断点续传就靠它
├── cache/        远端版本列表等 JSON，默认存一天
└── .locks/       并发安装时的锁
```

`ENVXX_HOME` 可以改位置。

国内网络慢的话留了镜像变量：

- `ENVXX_GITHUB_MIRROR`：GitHub 网页和 Release 下载
- `ENVXX_GITHUB_API`：GitHub API
- `ENVXX_GITHUB_RAW`：raw.githubusercontent.com
- `ENVXX_NODE_DIST`：nodejs.org
- `ENVXX_CCSWITCH_MIRROR`：CC Switch 自己的 CDN，默认指向 `dl.ccswitch.io`

Go 走 `dl.google.com`，JDK 走 Adoptium 的 API，两个都是直连，不在镜像变量覆盖的范围内。

关于 CC Switch：官方 CDN 只放了 v4.0.29 之后的文件。老版本还是从 GitHub 取，所以下载先试镜像，404 再回落。版本列表走的是 GitHub 的 tags 接口，四十多 KB 一页，比 releases 接口的几 MB 轻得多。

MobaXterm 没有 API，下载地址里那段数字是构建号，从版本号推不出来。`xterm` 的版本列表是抓官网下载页拿的。它的 changelog 有完整历史和日期，但只给最新两个稳定版挂下载链接，旧版本在列表里标成 `archived`，指定安装会直接报错，不会给你一个死链。另外它只有 Windows 版，其他平台会明确拒绝。

dufs 默认会换掉自带的简陋界面，用 [mikigo/dufs-shadcn-assets](https://github.com/mikigo/dufs-shadcn-assets) 那套 shadcn 皮肤。第一次 `envxx dufs` 时把资源包下到 `~/.envxx/tools/dufs/.assets`，之后直接用。你自己写了 `--assets` 就以你的为准，其他参数原样透传给 dufs。资源包拿不到时静默退回自带界面，不会因为网络问题让命令失败。

Claude Code 走的是 Open VSX，不是 VSCode 官方插件市场。两边是同一批构建，我核对过大文件字节一致，但 Open VSX 有不需要登录的 REST API。opencode 和 CC Switch 都是直接取 GitHub Release 里的官方压缩包，没有二次打包。

GitHub 未登录限流每小时 60 次。设个 `GITHUB_TOKEN` 能提到 5000，反正不要钱。

大文件支持断点续传，断了重跑就行，已经下过的部分不会丢。
