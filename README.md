# EnvXX

我不喜欢往系统里装东西。

装个 Python，注册表、PATH、开始菜单快捷方式全给你安排上，卸载时还留一堆东西。换台电脑或者重装一次系统，这些工具又得挨个下一遍、配一遍。EnvXX 就是冲着这件事写的：运行时全部下载到 `~/.envxx`，解压完就能用，不要了删目录就行，系统里什么都不留。

目前支持的工具：

| 工具 | 版本选择 | 默认入口 | 其他入口 |
|---|---|---|---|
| Python | `python3.11` / `python3.11.9` | `python` | `pip` |
| Node.js | `node22` / `node22.14.0` | `node` | `npm`、`npx` |

这张表还会继续加。

```console
$ envxx python3.11 -c "print('hello')"
installing python 3.11.18 (cpython-3.11.18+20261110-x86_64-pc-windows-msvc-install_only.tar.gz)
hello
```

第一次用某个版本时会自动下载、校验、解压，之后直接复用。命令名自带版本号，不用先切换再运行。

## 安装

```console
$ uv tool install envxx      # 或者 pipx install envxx
```

想从代码仓库直接跑：

```console
$ uv venv && uv pip install -e ".[dev]"
$ python -m envxx --help
```

## 用法

```console
$ envxx python3.11 -m pip install requests
$ envxx node22 --version
$ envxx run node@22:npm -- install express
```

Python 的 `install_only` 包里不带 `pip.exe`，所以 `-m pip` 这种调用方式是常态。`run` 是通用写法，`工具@版本:入口` 可以指定除默认入口外的其他程序，比如上面的 npm。

版本号可以写完整版本 `python3.11.9`，也可以只写 `python3.11` 或者 `node22`。写不全的时候优先用本地已安装的匹配版本，没有就去远程版本列表里找最高的那个。

管理本地文件：

```console
$ envxx python search        # 当前平台可用的远程版本
$ envxx python list          # 已经下载的版本
$ envxx python install 3.12  # 只安装，不运行
$ envxx python uninstall 3.11
$ envxx python where 3.11    # 启动器的绝对路径
```

`install` 必须写版本；`uninstall` 和 `where` 不写就作用于当前最高的已装版本。

`search` 里 Node 每个大版本只列最新的补丁版本（24.22.3 而不是 24 下面每一条），但精确到补丁的版本号照样能装。

## 目录

```
~/.envxx/
├─ tools/python/3.11.18/
├─ tools/node/22.14.0/
├─ cache/            # 远程版本索引，缓存 24 小时
├─ downloads/        # 校验过的压缩包
├─ .locks/           # 按版本加锁，避免并发重复下载
└─ shims/            # 预留给以后写 PATH 转发脚本
```

`ENVXX_HOME` 可以换掉整个目录的位置。国内网络下载慢的话，`ENVXX_GITHUB_API`、`ENVXX_GITHUB_MIRROR`、`ENVXX_GITHUB_RAW` 和 `ENVXX_NODE_DIST` 可以指向镜像。GitHub API 每小时只给 60 次未认证请求，设了 `GITHUB_TOKEN` 会宽松很多。

## 版本来源

Python 用 [python-build-standalone](https://github.com/astral-sh/python-build-standalone) 的 `install_only` 包，校验值是 release 里 asset 自带的 sha256 digest。

Node.js 从 [nodejs.org/dist](https://nodejs.org/dist) 下载，只取 LTS，用同目录的 `SHASUMS256.txt` 校验。低于 20 的版本不显示。

两边都只保存当前平台的构建，不会把其他系统的包一起拽下来。
