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
| Claude Code | `claude` | `claude` | Open VSX 上的 VSIX |
| opencode | `opencode` | `opencode` | GitHub Release 压缩包 |
| CC Switch | `cc-switch` | `cc-switch` | GitHub Release 便携版 |
| MobaXterm | `xterm` | `xterm` | mobatek.net 便携版 |
| Windows Terminal | `wt` | `wt`、`WindowsTerminal` | GitHub Release 便携版 |
| Notepad-- | `notepad--`、`ndd` | `notepad--` | GitHub Release 便携版 |
| MarkText | `marktext`、`mt` | `marktext` | GitHub Release 便携版 |
| DBeaver | `dbeaver` | `dbeaver` | GitHub Release 便携版 |
| Git for Windows | `git` | `git`、`scalar` | GitHub Release 便携版 |
| dufs | `dufs` | `dufs` | GitHub Release 压缩包 |

另外几个只下载安装包、不代你安装的：

| 工具 | 版本写法 | 来源 |
| --- | --- | --- |
| VS Code | `vscode`、`code` | update.code.visualstudio.com |
| 7-Zip | `7zip`、`7z` | 7-zip.org |
| 微信 | `wechat`、`weixin` | pc.weixin.qq.com |
| 企业微信 | `wecom`、`wechatwork` | work.weixin.qq.com |

Python、Node、Go、JDK 属于运行时，多个版本可以并存：`python3.11` 和 `python3.12` 各占一个目录，互不干扰。后面几个是应用，留最新版就够。

JDK 只列 17 以上的 LTS 线加上最新的特性版本，Adoptium 还在发的 Java 8、11 不会出现在 `search` 里；`jdk` 的默认版本是最新的那个，要 LTS 就写 `jdk21`。macOS 上的包是 bundle 布局，入口在 `Contents/Home/bin/java`，EnvXX 自己会找对位置。Go 的发布候选会标成 prerelease，`install` 不带版本号时不会挑到它们。

版本多的运行时（Go、JDK、Node）默认每个版本线只显示最新一个补丁版，比如 Go 显示 `1.27.4` 而不是 1.27 线的全部；`search --all` 才是完整列表。

Python 走的是 Astral 的官方索引（`releases.astral.sh` 的 NDJSON，uv 用的也是这个源），一次请求拿到全部 500 多个构建，从 3.8 到 3.16 都在内。这比翻 GitHub release 靠谱：python-build-standalone 的最新 release 只打包还在维护的版本线，3.8/3.9/3.10 早就不在里面了，用 GitHub API 找它们得翻很多页而且不一定翻得到。索引 20MB，缓存一天，第一次用会慢一些。索引里每个构建都带 sha256，下载会校验。

加新工具不用动命令行解析。写一个 provider，登记进注册表就行。ripgrep、fd、fzf 这些单文件工具都在候选名单里，只是我还没用到。

## 命令

```bash
envxx init                     # 在当前目录建项目级 .envxx
envxx <tool> search            # 看远端有哪些版本
envxx <tool> search --all      # 看完整版本历史
envxx <tool> list              # 看本地已经下了哪些
envxx <tool> install 3.11.9    # 只下载不运行
envxx <tool> update            # 升到最新（应用类）
envxx <tool> where             # 打印入口的绝对路径
envxx <tool> uninstall 3.11.18 # 删除某个版本（应用类可简写 rm）
```

版本号可以直接跟在工具名后面，管理命令跟在后面也行：

```bash
envxx python3.12 install       # 等同 envxx python install 3.12
envxx python3.12 where         # 等同 envxx python where 3.12
envxx python3.12 list          # 版本无意义，等同 envxx python list
```

`search` 默认只列近期版本：应用的列表取最新 10 条，多出来的会提示用 `--all`。所有列表（`search`、`search --all`、`list`）都是新版本在前。`--all` 到底有多全取决于工具——opencode 会去翻完整的 tag 历史，其余几个本来就是全量。

`envxx python3.11` 这种写法，本地没有 3.11 时会自动拉最新补丁版再执行，不用先 install。

想直接跑应用，写名字就行：`envxx claude`。带上参数也一样：`envxx node -v` 会真的调用 node。裸的 `envxx node` 走的是子命令帮助，不会去执行。

要给同一个工具指定别的入口，直接写入口名就行。Python 带 `pip`，Node 带 `npm`、`npx`，Go 带 `gofmt`：

```bash
envxx python3.11 pip install requests
envxx node22 npm run dev
envxx node22 npx create-vite
envxx go1.27 gofmt -l .
```

JDK 的默认入口就是 `java`，直接跟参数即可，不要重复写入口名：

```bash
envxx jdk21 --version          # 对
envxx jdk21 javac -version     # 需要另一个入口时才写
```

## 存储位置

所有东西默认在 `~/.envxx`，按工具类型分两个目录：

```
~/.envxx/
├── runtime/      运行时：python、node、go、jdk
├── app/          应用：claude、dufs、git、vscode……
├── downloads/    下载缓存，断点续传就靠它，跨项目共用
├── cache/        远端版本列表等 JSON，默认存一天
└── .locks/       并发安装时的锁
```

`ENVXX_HOME` 可以改位置。

### 每个项目一套运行时

项目里需要固定版本的运行时，又不希望污染全局的话：

```bash
cd my-project
envxx init
```

会在当前目录建 `.envxx/runtime/`，并把 `.envxx/` 追加进 `.gitignore`。之后在这个目录（以及它的任何子目录）里跑 `envxx python3.11`，用的是项目内那一份。

**只有运行时走项目级。** 应用（claude、git、vscode 这些）永远是机器级的，装到一个版本就够了，没有理由每个仓库一份：

```
my-project/.envxx/
├── runtime/      只有运行时
└── .project
```

`downloads/` 和 `cache/` 也不进项目目录：同一个 CPython 包 20MB，两个仓库各下一遍没有意义。项目里装 python 时，包从全局 `downloads/` 取，解压到项目 `runtime/`。

判断顺序是：`ENVXX_HOME` → 从当前目录向上找到的 `.envxx`（仅运行时） → `~/.envxx`。

`ENVXX_HOME` 排在最前面是故意的：它是每次调用显式指定的，CI 里设了它就不会因为仓库里恰好有个 `.envxx` 而换地方，也不会去找项目 store。

向上查找只认带 `.project` 标记文件的目录，所以一个碰巧叫 `.envxx` 的目录不会被误当成 store。`envxx init` 发现已有目录但不是它建的，会报错退出，不会覆盖。

`runtime/` 里放的是可执行文件。`init` 自动写 `.gitignore` 是为了挡住误提交，但挡不住一个本来就带着工具二进制的仓库——clone 别人的项目后就地跑 `envxx` 之前，先看一眼 `.envxx/` 里有什么。

老版本的 store 用 `tools/` 平铺，第一次运行新版本时会自动迁移：运行时进 `runtime/`，应用进 `app/`，项目 store 里的应用会被搬到全局。

## 只下载安装包的工具

有些软件官方只提供安装程序，没有绿色版。这类工具 EnvXX 只负责下载，不代你安装，也不声称删目录就能卸载：

```bash
envxx wechat install
```

它会把 `WeChatWin_4.2.0.exe` 下到 store 的 `downloads/` 里，然后把绝对路径打印出来，你双击自己装。

```bash
envxx 7zip list      # 已经下过哪些安装包
envxx 7zip where     # 安装包放在哪
```

注意几点：

- `list` 列的是 `downloads/` 里的安装包，不是 `tools/` 里的解包版本——这类工具根本不会在 `tools/` 下建目录。
- `where` 在还没下载时会提示先 `install`。
- 重复 `install` 不会重新下载，文件已经在就跳过。这类工具没有多版本并存的概念，`downloads/` 里同名文件只会有最新那一份。

微信和企业微信没有可查的历史版本，页面上只挂当前这一版，所以 `search` 只有一行。VS Code 和 7-Zip 能列出全部版本或当前构建。VS Code 在 Windows 上给的是 user 安装包（不需要管理员权限），macOS 给的是 zip。

Git for Windows 用的是 MinGit（`MinGit-*.zip`），不是安装器也不是 PortableGit。后两者一个要跑安装向导、一个是自解压 exe，只有 MinGit 是普通 zip，解开就能用。它是精简构建，没有 GUI 和 Perl，但 `git` 本身是完整的。压缩包是平铺的，`cmd/`、`usr/`、`ucrt64/` 直接在根，入口是 `cmd/git.exe`。

它的版本号带重打包序号，比如 `2.56.0.windows.4`。这不是噪音：`2.56.0` 被重新打包过四次，`v2.56.0.windows.1` 到 `.4` 是四个不同的构建，所以版本号保留完整形式。`search` 默认每个上游版本只显示最新一次重打包，`--all` 才列出全部。装的时候也注意文件名的规律：`v2.56.0.windows.1` 对应 `MinGit-2.56.0-64-bit.zip`（第一次重打包不带序号），而 `.4` 对应 `MinGit-2.56.0.4-64-bit.zip`。

## 用 pip 装进去的东西

`pip install` 装到某个 Python 里的控制台脚本，可以按名字直接跑。前提是它确实在那个 Python 的 `Scripts/`（Unix 上是 `bin/`）里：

```bash
envxx python3.11 pip install black
envxx python3.11 black .        # 找到 Scripts/black.exe
```

名字找不到时不会被吞掉，仍然按普通参数交给默认入口，所以 `envxx python3.11 script.py` 行为不变。这也意味着如果你在当前目录有个和参数同名的可执行文件或包，Python 会按自己的规则处理它。

## 几个工具的细节

国内网络慢的话留了镜像变量：

- `ENVXX_GITHUB_MIRROR`：GitHub 网页和 Release 下载
- `ENVXX_GITHUB_API`：GitHub API
- `ENVXX_GITHUB_RAW`：raw.githubusercontent.com
- `ENVXX_NODE_DIST`：nodejs.org
- `ENVXX_CCSWITCH_MIRROR`：CC Switch 自己的 CDN，默认指向 `dl.ccswitch.io`

Go 走 `dl.google.com`，JDK 走 Adoptium 的 API，两个都是直连，不在镜像变量覆盖的范围内。

关于 CC Switch：官方 CDN 只放了 v4.0.29 之后的文件。老版本还是从 GitHub 取，所以下载先试镜像，404 再回落。版本列表走的是 GitHub 的 tags 接口，四十多 KB 一页，比 releases 接口的几 MB 轻得多。

MobaXterm 没有 API，下载地址里那段数字是构建号，从版本号推不出来。`xterm` 的版本列表是抓官网下载页拿的。它的 changelog 有完整历史和日期，但只给最新两个稳定版挂下载链接，旧版本在列表里标成 `archived`，指定安装会直接报错，不会给你一个死链。另外它只有 Windows 版，其他平台会明确拒绝。

Windows Terminal 走 `microsoft/terminal` 的 releases，只收稳定版：预览版靠 `prerelease` 标记和资产名里的 `WindowsTerminalPreview` 双重过滤，所以 `1.26.x` 这种只在预览通道有的一律不出现。它的版本号是四段（`1.25.3131.0`），`wt` 只给 Windows。装好之后有两个入口：`wt` 是命令行前端（分屏、开新标签），`WindowsTerminal` 是 GUI 本体。

Notepad-- 只收了 Windows 便携包。它发的 macOS 资产是 `.dmg` 安装镜像，Linux 资产停在 v3.8 且命名不统一，两者都不符合"解压就能跑"的模型。arm64 便携包只有部分版本附带（目前只有 3.9.1），所以 arm64 机器上 `search` 只列真正有对应资产的版本，不会给一个必然 404 的下载。

MarkText 是 Electron 应用，Windows 和 macOS 都有 zip，Linux 给 tar.gz。它的压缩包是**扁平**的——`marktext.exe` 和 Electron 运行时文件直接在根目录，没有外层文件夹，所以安装时不剥层。这个项目还在发 `v0.24.0-rc.*`，那些会被过滤掉，只列稳定版。它是少数提供 `SHA256SUMS.txt` 的项目，下载会校验。

DBeaver 的 Windows 和 Linux 有 zip/tar.gz，macOS 只有 dmg，所以 macOS 上会明确报不支持。压缩包解开是一个 `dbeaver/` 目录，里面自带 JRE（约 194MB），安装时剥掉这层。

dufs 默认会换掉自带的简陋界面，用 [mikigo/dufs-shadcn-assets](https://github.com/mikigo/dufs-shadcn-assets) 那套 shadcn 皮肤。第一次 `envxx dufs` 时把资源包下到 `~/.envxx/tools/dufs/.assets`，之后直接用。你自己写了 `--assets` 就以你的为准，其他参数原样透传给 dufs。资源包拿不到时静默退回自带界面，不会因为网络问题让命令失败。

Claude Code 走的是 Open VSX，不是 VSCode 官方插件市场。两边是同一批构建，我核对过大文件字节一致，但 Open VSX 有不需要登录的 REST API。opencode 和 CC Switch 都是直接取 GitHub Release 里的官方压缩包，没有二次打包。

GitHub 未登录限流每小时 60 次。设个 `GITHUB_TOKEN` 能提到 5000，反正不要钱。

大文件支持断点续传，断了重跑就行，已经下过的部分不会丢。安装中断留下的残缺目录，下次 `install` 会检测到并自动重装。

## 发布

版本号只在 `envxx/__init__.py` 里写一次。`envxx --version` 读它，`pyproject.toml` 用 `dynamic = ["version"]` 从它读，打包出来的 zip 名用 tag。

tag 是同一个数字的第二份拷贝，两份会漂移：改了代码忘了改 tag，或者反过来。两道保险：

```bash
scripts/release.sh --dry-run   # 读 __version__，告诉你将要打的 tag
scripts/release.sh --push      # 打 tag 并推送，交给 CI
```

脚本要求工作区干净、tag 不重复，版本号直接从代码里读，不用手敲。

CI 在 tag 触发时会比对 tag 和 `__version__`，不一致直接失败，不会把版本号对不上的包发出去。手动触发（`workflow_dispatch`）没有 tag 可比，跳过这项检查。
