# EnvXX

我习惯让电脑保持干净。除了系统自带的东西，能不装就不装。要用 Python，就解压一个免安装版；要用 Node，也一样。没有安装向导，没有注册表垃圾，也没见过卸载后还剩 300MB 的目录。

这套习惯有个代价：换一台电脑，一切从头来。翻下载页、认准架构、解压、配 PATH，一个个弄。我换过几次机器，每次都在做同样的事，索性写成工具。

EnvXX 只干一件事：把官方发布的绿色版下到 `~/.envxx`，然后按需调用。想清干净，删掉这个目录就够了。

```bash
envxx python3.11 -m pip install requests   # 本地没有 3.11 就先下再执行
envxx node22 -v
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

`<版本>` 是 tag 去掉 `v`，比如 `v1.0.2` 对应 `1.0.2-linux-x64.zip`。文件名带版本，`latest/download/` 这种固定路径就用不了了，先问一下 API：

```bash
version=$(curl -s https://api.github.com/repos/mikigo/EnvXX/releases/latest \
  | grep -o '"tag_name": *"v[^"]*"' | cut -d'"' -f4); version=${version#v}
curl -L -o envxx.zip "https://github.com/mikigo/EnvXX/releases/latest/download/${version}-linux-x64.zip"
unzip envxx.zip
chmod +x "${version}-linux-x64/envxx" && sudo mv "${version}-linux-x64/envxx" /usr/local/bin/
```

zip 里带了 Unix 权限位，`unzip` 解出来的 Linux/macOS 二进制本来就是可执行的，`chmod` 只是保险。

每个二进制都是自包含的，typer、rich、httpx 全打在里面，本机不需要任何 Python。

从源码装也行：

```bash
pip install -e .
```

依赖只有 typer、rich、httpx，Python 3.10 起步。

## 现在支持

| 工具 | 版本写法 | 入口 | 来源 |
| --- | --- | --- | --- |
| Python | `python3.11`、`python3.11.9` | `python`、`pip` | python-build-standalone |
| Node.js | `node22`、`node22.14.0` | `node`、`npm`、`npx` | nodejs.org LTS |
| Claude Code | `claude` | `claude` | Open VSX 上的 VSIX |
| opencode | `opencode` | `opencode` | GitHub Release 压缩包 |
| CC Switch | `cc-switch` | `cc-switch` | GitHub Release 便携版 |
| MobaXterm | `xterm` | `xterm` | mobatek.net 便携版 |
| dufs | `dufs` | `dufs` | GitHub Release 压缩包 |

Python 和 Node 属于运行时，多个版本可以并存：`python3.11` 和 `python3.12` 各占一个目录，互不干扰。后面几个是应用，留最新版就够。

加新工具不用动命令行解析。写一个 provider，登记进注册表就行。Go、JDK、ripgrep 都在候选名单里，只是我还没用到。

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

`search` 默认只列近期版本：应用的列表倒序取前 10 条，多出来的会提示用 `--all`。`--all` 到底有多全取决于工具——opencode 会去翻完整的 tag 历史，其余几个本来就是全量。

`envxx python3.11` 这种写法，本地没有 3.11 时会自动拉最新补丁版再执行，不用先 install。

想直接跑应用，写名字就行：`envxx claude`。带上参数也一样：`envxx node -v` 会真的调用 node。裸的 `envxx node` 走的是子命令帮助，不会去执行。

要给同一个工具指定别的入口，直接写入口名就行。Python 带 `pip`，Node 带 `npm`、`npx`：

```bash
envxx python3.11 pip install requests
envxx node22 npm run dev
envxx node22 npx create-vite
```

`envxx run` 是等价写法，用于脚本里拼接：

```bash
envxx run python@3.11:pip --version
envxx run node@22:npm --version
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

关于 CC Switch：官方 CDN 只放了 v4.0.29 之后的文件。老版本还是从 GitHub 取，所以下载先试镜像，404 再回落。版本列表走的是 GitHub 的 tags 接口，四十多 KB 一页，比 releases 接口的几 MB 轻得多。

MobaXterm 没有 API，下载地址里那段数字是构建号，从版本号推不出来。`xterm` 的版本列表是抓官网下载页拿的。它的 changelog 有完整历史和日期，但只给最新两个稳定版挂下载链接，旧版本在列表里标成 `archived`，指定安装会直接报错，不会给你一个死链。另外它只有 Windows 版，其他平台会明确拒绝。

dufs 默认会换掉自带的简陋界面，用 [mikigo/dufs-shadcn-assets](https://github.com/mikigo/dufs-shadcn-assets) 那套 shadcn 皮肤。第一次 `envxx dufs` 时把资源包下到 `~/.envxx/tools/dufs/.assets`，之后直接用。你自己写了 `--assets` 就以你的为准，其他参数原样透传给 dufs。资源包拿不到时静默退回自带界面，不会因为网络问题让命令失败。

Claude Code 走的是 Open VSX，不是 VSCode 官方插件市场。两边是同一批构建，我核对过大文件字节一致，但 Open VSX 有不需要登录的 REST API。opencode 和 CC Switch 都是直接取 GitHub Release 里的官方压缩包，没有二次打包。

GitHub 未登录限流每小时 60 次。设个 `GITHUB_TOKEN` 能提到 5000，反正不要钱。

大文件支持断点续传，断了重跑就行，已经下过的部分不会丢。

## 自己打包

打 `v*` 的 tag 会触发 `.github/workflows/release.yml`，六个平台各打一个二进制，包成 `<版本>-<平台>.zip` 挂到 Release；也能手动跑一次，版本号填了就用填的，挂在 tag 上就用 tag，都没有则用 `dev-<commit>`，只在 Actions 里留构建产物。

用的是 PyInstaller，它不能交叉编译，所以每个平台在自己 runner 上打自己的。Linux 特意选 22.04 而不是最新版，这样打出来的 ELF 只要求 glibc 2.35，老一点的发行版也能跑。
