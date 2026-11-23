# EnvXX

[![release](https://img.shields.io/github/v/release/mikigo/EnvXX?include_prereleases&sort=semver)](https://github.com/mikigo/EnvXX/releases)
[![license](https://img.shields.io/github/license/mikigo/EnvXX)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)

跨 Windows、Linux、macOS 的免安装运行时管理器。把官方发布的绿色版下载到同一个目录，按需调用，删掉目录就等于卸载。

```bash
envxx python3.11 -m pip install requests
envxx node22 -v
envxx go1.27 version
envxx claude
```

没有安装向导，不写注册表，卸载后不留残留目录。

## 为什么做这个

配一台新机器意味着一件事：下载 Python、Node、Go 和 JDK，每个都认准架构，解压到某个地方，再把 PATH 配好。换下一台机器，同样的活再来一遍。

EnvXX 把这件事做一次，产物放在 `~/.envxx`。每个工具都是上游官方构建，没有二次打包；每个版本独占一个目录，多个版本可以并存。

```bash
rm -rf ~/.envxx   # 卸载完成
```

## 安装

从 [Releases](https://github.com/mikigo/EnvXX/releases/latest) 下载对应平台的压缩包，解压后把二进制放进 PATH。

| 系统 | 压缩包 | 二进制 |
| --- | --- | --- |
| Windows x64 | `<版本>-windows-x64.zip` | `<版本>-windows-x64/envxx.exe` |
| Windows arm64 | `<版本>-windows-arm64.zip` | `<版本>-windows-arm64/envxx.exe` |
| Linux x64 | `<版本>-linux-x64.zip` | `<版本>-linux-x64/envxx` |
| Linux arm64 | `<版本>-linux-arm64.zip` | `<版本>-linux-arm64/envxx` |
| macOS Apple Silicon | `<版本>-macos-arm64.zip` | `<版本>-macos-arm64/envxx` |
| macOS Intel | `<版本>-macos-x64.zip` | `<版本>-macos-x64/envxx` |

`<版本>` 是 tag 去掉 `v`：tag `v1.8.0` 对应 `1.8.0-linux-x64.zip`。文件名带版本，所以 `releases/latest/download/...` 这种固定路径用不了，得先问 API：

```bash
version=$(curl -s https://api.github.com/repos/mikigo/EnvXX/releases/latest \
  | grep -o '"tag_name": *"v[^"]*"' | cut -d'"' -f4); version=${version#v}
curl -L -o envxx.zip "https://github.com/mikigo/EnvXX/releases/latest/download/${version}-linux-x64.zip"
unzip envxx.zip
chmod +x "${version}-linux-x64/envxx" && sudo mv "${version}-linux-x64/envxx" /usr/local/bin/
```

二进制是自包含的：typer、rich、httpx 都打在里面，目标机器不需要装 Python。

从源码安装：

```bash
pip install -e .
```

## 快速上手

```bash
envxx python3.11 -m pip install requests   # 本地没有 3.11 会先下载
envxx node22 -v
envxx go1.27 version
envxx jdk21 --version
```

工具名和版本连在一起写：`python3.11`、`node22`、`go1.27`、`jdk21`。别名也认：`golang1.27`、`java21`、`temurin21`、`nodejs22`。

## 支持的工具

### 运行时

多个版本可以并存，`python3.11` 和 `python3.12` 各占一个目录。

| 工具 | 版本写法 | 入口 | 来源 |
| --- | --- | --- | --- |
| Python | `python3.11`、`python3.11.9` | `python`、`pip` | python-build-standalone |
| Node.js | `node22`、`node22.14.0` | `node`、`npm`、`npx` | nodejs.org LTS |
| Go | `go1.27`、`go1.27.4` | `go`、`gofmt` | go.dev |
| JDK | `jdk21`、`java21` | `java`、`javac`、`jar` | Adoptium Temurin |

### 便携应用

解包即用，留最新版就够。

| 工具 | 版本写法 | 入口 | 来源 |
| --- | --- | --- | --- |
| Claude Code | `claude` | `claude` | Open VSX |
| opencode | `opencode` | `opencode` | GitHub Release |
| CC Switch | `cc-switch` | `cc-switch` | GitHub Release |
| MobaXterm | `xterm` | `xterm` | mobatek.net |
| Windows Terminal | `wt` | `wt`、`WindowsTerminal` | GitHub Release |
| Notepad-- | `notepad--3.9`、`ndd3.9` | `notepad--` | GitHub Release |
| MarkText | `marktext0.23`、`mt0.23` | `marktext` | GitHub Release |
| DBeaver | `dbeaver` | `dbeaver` | GitHub Release |
| dufs | `dufs` | `dufs` | GitHub Release |

### 安装器应用

只下载并打开安装程序，装不装由你决定。EnvXX 不代劳，因为这类软件会往 Program Files 里写东西，做不到"删目录即卸载"。

| 工具 | 版本写法 | 来源 |
| --- | --- | --- |
| Git for Windows | `git` | git-scm.com |
| VS Code | `vscode`、`code` | update.code.visualstudio.com |
| 7-Zip | `7zip`、`7z` | 7-zip.org |
| 微信 | `wechat`、`weixin` | pc.weixin.qq.com |
| 企业微信 | `wecom`、`wechatwork` | work.weixin.qq.com |

## 用法

### 管理版本

```bash
envxx <tool> search            # 远端有哪些版本
envxx <tool> search --all      # 完整历史（默认每个版本线只显示最新补丁）
envxx <tool> list              # 本地已下载
envxx <tool> install 3.11.9    # 只下载不运行
envxx <tool> update            # 升到最新（应用类）
envxx <tool> where             # 入口的绝对路径
envxx <tool> uninstall 3.11.18 # 删除某个版本（应用类可简写 rm）
```

版本号也可以直接跟在工具名后面：

```bash
envxx python3.12 install       # 等同 envxx python install 3.12
envxx python3.12 where         # 等同 envxx python where 3.12
envxx python3.12 list          # 版本无意义，等同 envxx python list
```

所有列表都是新版本在前。`search` 每个版本线只显示最新补丁，`--all` 才是全部。

### 运行工具

没装的版本会在第一次调用时自动下载：

```bash
envxx python3.11 script.py     # 需要时先装 3.11，再执行
```

应用直接写名字：

```bash
envxx claude
envxx node -v                  # 参数会真的传给 node
```

裸的工具名（`envxx node`）显示子命令帮助，不会执行。

### 其他入口

Python 带 `pip`，Node 带 `npm`、`npx`，Go 带 `gofmt`：

```bash
envxx python3.11 pip install requests
envxx node22 npm run dev
envxx node22 npx create-vite
envxx go1.27 gofmt -l .
```

默认入口不需要重复写。JDK 的默认入口是 `java`，所以 `envxx jdk21 --version` 是对的，`envxx jdk21 java --version` 不是。

`envxx run` 是脚本里拼命令用的等价写法：

```bash
envxx run python@3.11:pip --version
envxx run node@22:npm --version
```

### 不用每次写 envxx

```bash
envxx python3.10 set-path      # 生成 ~/.envxx/bin/python3.10.exe，并把 bin 目录加进 PATH
```

之后新开的终端里直接 `python3.10 script.py`。`envxx bin` 列出已生成的所有命令。

`set-path` 会检查 `~/.envxx/bin` 是否在 PATH 上，不在就自动加进去（已在则不动），不需要再手动跑一次 `envxx set-path ~/.envxx/bin`。

目录默认加在**最前面**，刚加进去的应该优先；放末尾用 `--append`。已经存在的条目不动，重复执行是幂等的。

摘掉一个目录用 `envxx unset-path <dir>`（等价于 `envxx set-path <dir> --remove`）。

启动器永远指向全局 store。PATH 是机器级的，指向项目里的副本会在项目删除后失效，所以项目内执行 `set-path` 会直接报错。`--remove` 用来删除。

### 环境变量

```bash
envxx set-env FOO bar          # 用户级：Windows 写注册表，其他平台写 shell rc
envxx set-env FOO --unset      # 删除
envxx set-env --list           # 看 envxx 设过哪些
```

`PATH` 会被拒绝——整条替换会丢掉其他所有条目，请用 `set-path`。每次写入前旧值备份到 `~/.envxx/.backup/`。

改动对新终端生效，已开的终端保留旧环境；命令会打印免重开的刷新方法。

### 项目级运行时

```bash
cd my-project
envxx init
```

在当前目录建 `.envxx/runtime/`，并把 `.envxx/` 追加进 `.gitignore`。从这个目录及其子目录运行 `envxx python3.11`，用的都是项目内那一份。

只有运行时能项目级。应用是机器级的——没有理由每个仓库带一份自己的文本编辑器。

```
my-project/.envxx/
├── runtime/
└── .project
```

`downloads/` 和 `cache/` 也不进项目目录：同一个 20 MB 的 CPython 包不该每个仓库下一遍。

查找顺序：`ENVXX_HOME` → 向上找到的 `.envxx`（仅运行时）→ `~/.envxx`。`ENVXX_HOME` 排最前是因为它每次调用都显式指定；CI 里设了它就不会被仓库里的 `.envxx` 带偏。

只有带 `.project` 标记的目录才算项目 store，一个碰巧叫 `.envxx` 的目录会被忽略。`envxx init` 发现目录不是它建的会报错退出，不会覆盖。

`runtime/` 里放的是可执行文件。`init` 写 `.gitignore` 是为了防止误提交，但挡不住刻意提交二进制的仓库——在 clone 下来的项目里跑 `envxx` 之前，先看一眼 `.envxx/` 里有什么。

老版本用平铺的 `tools/` 目录，第一次运行新版本时自动迁移：运行时进 `runtime/`，应用进 `app/`。

## 存储

```
~/.envxx/
├── runtime/      python、node、go、jdk
├── app/          claude、dufs、git、vscode……
├── downloads/    下载缓存，支持断点续传，跨项目共用
├── cache/        远端版本列表，缓存一天
└── .locks/       并发安装时的锁
```

`ENVXX_HOME` 可以改位置。

## 行为说明

### Python

版本目录来自 Astral 的官方索引（`releases.astral.sh`，uv 用的也是这个源）。一次请求返回全部 500 多个构建，从 3.8 到 3.16——GitHub release API 只列还在维护的版本线，3.8/3.9/3.10 在那里查不到。索引 20 MB，缓存一天。每个构建都带 sha256，下载时校验。

### JDK

只列 17 以上的 LTS 线加上最新特性版本；Adoptium 还在发 Java 8 和 11，但默认摆出来只是噪音。默认版本是最新那个，要 LTS 得写 `jdk21`。macOS 上的包是 bundle，入口在 `Contents/Home/bin/java`，EnvXX 会自己找对。

### 版本显示

版本多的工具（Go、JDK、Node）默认每个版本线只显示一行——`1.27.4` 而不是 1.27 的每个补丁。`search --all` 列出全部。

### Git for Windows

用官方安装器（`Git-*.exe`），和下载页一致。安装器会配好 shell 集成和凭据管理器，那是安装器自己的决定，不是 EnvXX 的。

版本号带重打包序号——`2.56.0.windows.1` 到 `.4` 是同一个上游版本的四个不同构建，所以保留完整 tag。`search` 每个上游版本只显示最新一次重打包，`--all` 全部列出。

### 安装器应用

```bash
envxx wechat install
```

下载到 `downloads/`，打印绝对路径，然后打开安装程序。装不装、怎么装都是你的事。关掉窗口不会丢什么——文件还在，随时能再打开。

stdio 不是终端时（脚本、CI）不会弹窗，只打印路径，否则流水线会卡在那里等人点。

`list` 报告的是 `downloads/` 里有什么，不是解包内容，因为这类工具根本不会创建 `runtime/` 或 `app/` 条目。`where` 打印安装包路径。重复 `install` 不会重新下载。

微信和企业微信没有版本历史——页面上只挂当前这一版，所以 `search` 只有一行。VS Code 和 7-Zip 能列版本。

### pip 安装的控制台脚本

装进运行时 `Scripts/`（或 `bin/`）的脚本可以按名字调用：

```bash
envxx python3.11 pip install black
envxx python3.11 black .
```

找不到的名字会当作普通参数透传，所以 `envxx python3.11 script.py` 行为不变。

## 配置

### 镜像

网络慢可以指向镜像：

| 变量 | 覆盖范围 |
| --- | --- |
| `ENVXX_GITHUB_MIRROR` | github.com 页面和 Release 下载 |
| `ENVXX_GITHUB_API` | api.github.com |
| `ENVXX_GITHUB_RAW` | raw.githubusercontent.com |
| `ENVXX_NODE_DIST` | nodejs.org/dist |
| `ENVXX_CCSWITCH_MIRROR` | CC Switch 自己的 CDN，默认 `dl.ccswitch.io` |

Go 从 `dl.google.com` 下载，JDK 走 Adoptium 的 API，两者都不在镜像变量覆盖范围内。

### 限流

GitHub API 未登录每小时 60 次，设 `GITHUB_TOKEN` 提到 5000。大文件支持断点续传，中断的安装会在下次运行时检测到并重做。

## 各工具的细节

**CC Switch** —— 官方 CDN 只放 v4.0.29 之后的文件，老版本还是从 GitHub 取：先试镜像，404 再回落。版本列表走 tags 接口（每页几十 KB）而不是 releases（每页几 MB）。

**MobaXterm** —— 没有 API。下载地址里的构建号无法从版本号推出，所以列表是抓下载页得到的。changelog 有完整历史，但只有最新两个稳定版挂链接；旧版本标记为 `archived`，安装会明确报错而不是给一个死链。仅 Windows。

**Windows Terminal** —— 只收稳定通道。预览版靠 `prerelease` 标记和 `WindowsTerminalPreview` 资产前缀双重过滤，所以即使某个预览版忘了打标记也会被排除。版本号四段（`1.25.3131.0`）。两个入口：`wt` 是命令行（分屏、开新标签），`WindowsTerminal` 是 GUI。

**Notepad--** —— 只收 Windows 便携包。它的 macOS 资产是 `.dmg` 安装镜像，Linux 资产停在 v3.8 且命名不统一，都不适合便携 store。arm64 包只有部分版本附带，所以 arm64 上 `search` 只列真正有对应资产的版本。

**MarkText** —— Electron 应用，Windows 和 macOS 有 zip，Linux 有 tar.gz。压缩包是扁平的：`marktext.exe` 和 Electron 运行时文件直接在根目录，没有外层文件夹，所以不剥层。发布候选（`v0.24.0-rc.*`）会被过滤掉。它提供 `SHA256SUMS.txt`，下载会校验。

**DBeaver** —— Windows 有 zip，Linux 有 tar.gz，macOS 只有 dmg；dmg 是安装镜像，所以 macOS 上明确报不支持。压缩包解开是单个 `dbeaver/` 目录，里面自带 JRE（约 194 MB），装的时候剥掉这层。

**dufs** —— 默认用 [mikigo/dufs-shadcn-assets](https://github.com/mikigo/dufs-shadcn-assets) 替换自带界面。资源包第一次运行时下到 `~/.envxx/tools/dufs/.assets`。你自己写了 `--assets` 就以你的为准；其他参数原样透传给 dufs。资源包拿不到时静默退回自带界面，而不是让命令失败。

**Claude Code** —— 走 Open VSX 而不是官方 VS Code 市场。两边是同一批构建（大文件字节一致），但 Open VSX 有不需要登录的 REST API。opencode 和 CC Switch 直接用 GitHub Release 里的官方压缩包。

## 开发

需要 Python 3.10+。

```bash
pip install -e ".[dev]"
python -m pytest -q
```

平台相关代码（shim 格式、shell rc 文件、注册表、桌面打开方式）只有真跑在对应系统上才会走到。本机只能覆盖一个平台，所以有一套交叉开关：

```bash
PYTHONPATH=tests python -m pytest -q -p cross_platform --cross-platform=linux
```

三种取值：`windows`、`linux`、`macos`。CI 在 Ubuntu 和 Windows 上各跑一遍，本地的 `--cross-platform` 用于在推送前确认另一半。

加工具只需写一个 provider 并注册，命令行解析是注册表驱动的，不用改。步骤见 `skills/envxx/references/adding-a-provider.md`。

Windows 的启动器 shim 是一个编译好的二进制，提交在 `envxx/data/` 下。改动 `scripts/shim/shim.c` 后需要重新编译：

```bash
cmd //c scripts/shim/build.bat
```

## 发布

版本号只写在一处：`envxx/__init__.py`。`envxx --version` 读它，`pyproject.toml` 通过 `dynamic = ["version"]` 读它，发布包名来自 tag。

tag 是同一个数字的第二份拷贝，两者会漂移。两道保险：

```bash
scripts/release.sh --dry-run   # 读 __version__，显示将要打的 tag
scripts/release.sh --push      # 打 tag 并推送，剩下交给 CI
```

脚本要求工作区干净、tag 不重复，版本号从代码里读而不是手敲。CI 在 tag 触发时还会比对 tag 和 `__version__`，不一致直接失败，版本号对不上的包发不出去。手动触发（`workflow_dispatch`）没有 tag 可比，会跳过这项检查。

## 许可证

[Apache-2.0](LICENSE)
