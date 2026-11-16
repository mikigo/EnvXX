# EnvXX

我这台电脑上除了系统自带的，几乎不装东西。需要 Python 就解压一个免安装版，需要 Node 也一样。换来的是干净：没有安装向导，没有注册表垃圾，也没有"卸载时残留了 300MB"这种事。

代价是换一台电脑就得重来一遍。找链接、下压缩包、解压、配 PATH，一个个来。这套流程我重复太多次，干脆写成工具。

EnvXX 只做一件事：把官方发布的绿色版下载到 `~/.envxx`，然后按需调用。想彻底清除就删掉这个目录，不留痕迹。

```bash
envxx python3.11 -m pip install requests   # 本地没有 3.11 就先下再执行
envxx node22 -v
envxx claude
```

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

Python 和 Node 是可以并存的运行时，`python3.11` 和 `python3.12` 各装各的，互不影响。后面几个是应用，只保留最新版就够了，多装的版本可以用 `update`、`rm` 收拾。

加新工具不需要动命令行解析，写一个 provider 就行。Go、JDK、ripgrep 这些都是候选，只是我还没用到。

## 命令

```bash
envxx <tool> search            # 看远端有哪些版本
envxx <tool> search --all      # 列表太长时用这个
envxx <tool> list              # 看本地已经下了哪些
envxx <tool> install 3.11.9    # 只下载不运行
envxx <tool> update            # 升到最新（应用类）
envxx <tool> where             # 打印入口的绝对路径
envxx <tool> rm 3.11.18        # 删除某个版本
```

`envxx python3.11` 这种写法会在本地没有 3.11 时自动拉最新补丁版再执行，不用先 install。

## 安装 EnvXX 自己

```bash
pip install -e .
```

依赖只有 typer、rich、httpx。

## 几个说明

所有东西都放在 `~/.envxx`，用 `ENVXX_HOME` 可以改位置。下载的中转文件、版本目录、临时目录都在里面，删目录等于全部卸载。

国内网络慢的话留了镜像变量：

- `ENVXX_GITHUB_MIRROR`：GitHub 网页和 Release 下载
- `ENVXX_GITHUB_API`：GitHub API
- `ENVXX_NODE_DIST`：nodejs.org
- `ENVXX_CCSWITCH_MIRROR`：CC Switch 自己的 CDN，默认已经指向 `dl.ccswitch.io`

关于 CC Switch：它的官方 CDN 只放了 v4.0.29 之后的文件，老版本仍然从 GitHub 取，所以下载会先试镜像，404 再回落到 GitHub。列表本身的版本来自 GitHub API 的 tags 接口，四十多 KB 一页，比 releases 接口那几 MB 轻得多。

MobaXterm 没有 API，下载地址里的那段数字是构建号，没法从版本号推导。所以 `xterm` 的版本列表是抓官网下载页拿的：它的 changelog 里有完整历史和日期，但只给最新两个稳定版挂下载链接，旧版本在列表里标成 `archived`，指定装会直接报错而不是给你一个死链。它也只有 Windows 版，其他平台会明确拒绝。

dufs 默认会换掉自带的简陋界面，用 [mikigo/dufs-shadcn-assets](https://github.com/mikigo/dufs-shadcn-assets) 那套 shadcn 皮肤。第一次运行 `envxx dufs` 时会把资源包下到 `~/.envxx/tools/dufs/.assets`，之后直接用。你自己写了 `--assets` 就以你的为准，其他参数一律原样透传给 dufs。资源包拿不到时会静默退回 dufs 自带界面，不会因为网络问题让命令失败。

GitHub 未登录限流每小时 60 次。设个 `GITHUB_TOKEN` 能提到 5000，反正不用花钱。

Claude Code 走的是 Open VSX，不是 VSCode 官方插件市场。两边是同一批构建，我核对过大文件字节一致，但 Open VSX 有不需要登录的 REST API。opencode 和 CC Switch 都是直接取 GitHub Release 里的官方压缩包，没有二次打包。

大文件支持断点续传，断了重跑就行，已经下过的部分不会丢。
