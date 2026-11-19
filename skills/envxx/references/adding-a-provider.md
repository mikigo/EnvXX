# 给 EnvXX 加一个 provider

一个工具由三部分组成：`ToolSpec`（声明，纯数据）、`Provider` 子类（行为和网络）、注册表里的一个键。安装流程只读 `InstallPlan`，不认识具体工具。

先读这两个模板，它们覆盖了大多数形态：

- `envxx/providers/uv_provider.py`：GitHub release，二进制在压缩包根目录，`strip_top=False`。
- `envxx/providers/go_provider.py`：官方 JSON 清单，每个文件自带 sha256，六个平台都有。

目录结构（技能可用 `envxx/` 就是仓库根）：

```
envxx/providers/
├── base.py          基类，排序、入口查找、脚本发现都在这里
├── spec.py          ToolSpec / EntryPoint / Asset / InstallPlan
├── __init__.py      注册表 _PROVIDER_TYPES
└── <tool>_provider.py
```

## ToolSpec 的每个字段

```python
ToolSpec(
    name="uv",                          # 命令里的名字，也是 ~/.envxx/tools/<name>/
    kind="runtime",                     # runtime 可多版本并存；app 只留最新
    versioned=True,                     # 有版本号的工具都是 True
    summary="uv, the Python package manager",   # envxx --help 里那一行
    selector_prefixes=("uv",),          # 'uv0.13' 靠这个前缀匹配
    aliases=(),                         # 额外别名，和 name 等价
    entrypoints=(                       # 用户能直接调的命令名
        EntryPoint("uv", "uv"),
        EntryPoint("uvx", "uvx"),
    ),
    default_entrypoint="uv",            # 不写时用 entrypoints[0]
    script_dirs=(),                     # 包管理器往里装脚本的目录，见下
    checksum="shasums_file",            # api_digest | shasums_file | sha256_file | none
)
```

`selector_prefixes` 会编译成 `^<prefix>(\d+(\.\d+){0,2})$`。想支持 `nodejs22` 就写 `("node", "nodejs")`；想支持 `java21` 就写 `("jdk", "java")`。

`EntryPoint(name, relpath, kind="exe", module=None)`：

- `relpath` 是**相对于解包后版本目录**的路径，不含平台后缀，例如 `bin/go`。
- `kind="cmd"` 用于 `.cmd` 脚本（Windows 的 npm），会依次试 `.cmd`、`.exe`、无后缀。
- `module="pip"` 表示没有启动器文件时退化成 `<默认入口> -m pip`。
- `relpath` 里可以写 `{version}`，会在知道具体版本后替换（MobaXterm 那种把版本写进文件名的）。

`script_dirs`：`pip install -e .` 会往 Python 的 `Scripts/` 或 `bin/` 写控制台脚本，用户期望 `envxx python3.11 <脚本名>` 能找到它。把这个目录填进来，`Provider.script_path()` 会按名字查。只有会被人往里装东西的运行时（python）需要。

注意 `script_path()` 只回答"这个名字在不在"，不管它能不能跑。脚本自己在导入时会去找依赖，所以 `envxx python3.11 envxx` 只有在那个 Python 里装过 envxx 的依赖时才成立，否则报 `ModuleNotFoundError`。这不是 provider 该处理的事，文档里别把它写成无条件可用。

## Provider 子类的最小实现

```python
from ..errors import NetworkError
from .base import VersionedProvider, latest_per_line
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo


class FooProvider(VersionedProvider):
    spec = FOO_SPEC

    def _fetch_versions(self) -> list[VersionInfo]:
        # 顺序随意，基类会排成新版本在前
        from .. import http
        data = http.get_json(_TAGS_URL, "foo-tags-1")
        if not isinstance(data, list):
            raise NetworkError("unexpected foo tags payload")
        return [VersionInfo(version=_to_version(t["name"])) for t in data]

    def display_versions(self) -> list[VersionInfo]:
        # 仅当目录很长、需要折叠到每行一个版本线时才覆写
        return latest_per_line(self.search(), depth=2)

    def plan(self, version: str) -> InstallPlan:
        name = self._asset_name(version)
        return InstallPlan(
            version=version,
            asset=Asset(url=..., filename=name, format="zip", sha256_url=...),
        )
```

必须实现的只有 `_fetch_versions()` 和 `plan()`。其余都有默认实现。

### 数据类

`VersionInfo(version, channel="stable", lts=None, released=None, notes="", size=None)`
`channel="prerelease"` 会让 `install` 不带版本号时跳过它（Go 的 rc、Python 的 `3.16.0a2` 都这么做）。`notes` 显示在 channel 列里（Node 用它显示 LTS 代号，xterm 用 `archived` 标记不可下载的旧版）。

`Asset(url, filename, format, sha256=None, sha256_url=None, sha256_filename=None, size=None)`
`format` 只能是 `"zip"`、`"tar.gz"`、`"exe"`（`exe` 表示单文件，如 AppImage）。目前 `archive.py` **不支持 `.tar.xz` 和 `.7z`**；要用这类格式得先扩展它。

`InstallPlan(version, asset, strip_top=True, single_name=None)`
`strip_top` 剥掉压缩包最外层目录。**先解包看清楚再决定**：uv 的包里是 `uv.exe` 直接在根，所以 `False`；bun 的包是 `bun-windows-x64/bun.exe`，所以 `True`。

## 覆盖入口路径

默认实现在 Windows 上给 `relpath` 加 `.exe`，其余平台原样。需要特例时覆写：

```python
def entrypoint_candidates(self, name, version=None):
    candidates = super().entrypoint_candidates(name, version)
    if self.platform.os != "macos":
        return candidates
    return ["Contents/Home/" + n for n in candidates]   # JDK 的 bundle 布局
```

用 `super()` 再改前缀，别整个重写一遍，否则 Windows 的 `.exe` 逻辑会丢。这是 JDK provider 第一版踩过的坑。

## 平台映射

`Platform` 有 `os`（`windows`/`linux`/`macos`）和 `arch`（`x64`/`arm64`），`tag` 是 `windows-x64` 这种形式。每个工具对平台的叫法都不一样，在 provider 模块里放一张表：

| 工具 | x64 | arm64 |
| --- | --- | --- |
| Rust triple（uv、dufs、bat 等） | `x86_64-…` | `aarch64-…` |
| Go | `amd64` | `arm64` |
| Node | `x64`／`win-x64` | `arm64`／`win-arm64` |
| Adoptium | `x64` | `aarch64` |

`macos` 在 Rust triple 里叫 `apple-darwin`，在 Node 里叫 `darwin-*`，在 Adoptium 里叫 `mac`，在 Go 里叫 `darwin`。照抄资产名，不要凭印象推断。

## 校验

`checksum` 声明的是**怎么拿到 digest**，不是要不要校验：

- `api_digest`：payload 自带（Go 清单的 `sha256`、Adoptium 的 `checksum`、GitHub release API 的 `digest`）。填进 `Asset.sha256`。
- `shasums_file`：一个列表文件，行格式 `<hex>  <filename>`。填 `sha256_url` 和 `sha256_filename`。
- `sha256_file`：一个只含 hex 的文件。
- `none`：没有来源。

下载时 `http.download(expected=...)` 会校验，不匹配就报 `ChecksumError` 并删掉半成品。

## 版本号归一化

不同来源的版本写法不一致，统一成 `1.27.4` 这种纯数字点分形式：

- Go 的 `go1.27.4` → `1.27.4`
- Bun 的 `bun-v1.4.4` → `1.4.4`
- Adoptium 的 `21.0.13+9` → 用 `semver` 字段，剥掉 `+` 后面
- Node 的 `v22.14.0` → `22.14.0`

`version_key()` 只解析前面的数字段，`best_match()` 按前缀匹配，所以 `jdk21` 能找到 `21.0.13`。

## 排序

**不要在 provider 里排序。** `Provider.search()` 已经统一 `newest_first()`。需要折叠时覆写 `display_versions()` 并调用 `latest_per_line(self.search(), depth=N)`：

- `depth=1`：每行一个主版本（node 20/22/24、jdk 17/21/25）
- `depth=2`：每行一个次版本（go 1.26/1.27、uv 0.12/0.13、bun 1.3/1.4）

`search_all()` 默认返回完整目录，不用覆写，除非获取全量需要额外请求。

## 注册

`envxx/providers/__init__.py`：

```python
from .foo_provider import FooProvider

_PROVIDER_TYPES: dict[str, type[Provider]] = {
    ...
    "foo": FooProvider,
}
```

同时在 `__all__` 里加上 `"FooProvider"`。注册后命令行的子命令、选择器、帮助列表全部自动出现，不需要改 `cli.py`。

## 测试

放 `tests/test_runtimes.py`（新结构化运行时）或 `tests/test_providers.py`（其余）。单测不能联网——`tests/conftest.py` 里有个 autouse fixture，任何没打 `@pytest.mark.network` 的测试碰网络都会失败。用假的 payload：

```python
def test_foo_lists_versions(win, monkeypatch):
    tags = [{"name": "v1.2.3"}, {"name": "v1.2.2"}, {"name": "nightly"}]
    monkeypatch.setattr(
        "envxx.http.get_json",
        lambda url, *a, **k: tags if url.endswith("page=1") else [],
    )
    versions = [i.version for i in FooProvider(win).search()]
    assert versions == ["1.2.3", "1.2.2"]   # 新版本在前，垃圾 tag 被过滤
```

**分页的桩用 `endswith("page=1")`，不要用 `"page=1" in url`。** 后者会匹配到 `per_page=100`，第一页满 100 条时永远翻不完，测试挂死在循环里。这个坑是实际踩到的。

值得覆盖的点：

- 版本归一化（前缀、元数据、prerelease 标记）
- 六平台资产名（参数化 `Platform(os, arch)`）
- `strip_top` 和入口路径
- checksum 的各来源
- 畸形 payload（缺字段、类型不对）要报 `NetworkError` 而不是 `KeyError`

全绿之后再做一次真实安装：

```bash
envxx <tool> install <version>    # 下载、解包、校验入口
envxx <tool> where                # 确认路径
envxx <tool>0.x --version         # 选择器形式，真的能跑
```

单测证明解析逻辑对，真实安装才能证明包结构和你想的一样。

## 在写代码之前验证来源

三条经验，都是评估里花了半小时才弄明白的：

**先看 tags 是不是只有版本号。** ripgrep 的 tag 空间混着 `ignore-0.4.34`、`termcolor-0.3.6` 这类 crate tag，第一页 100 条里一个版本都没有。这种情况要走 `/releases` 接口，它同时带资产名、size 和 `digest`，代价是每页大几 MB。判断方法：拉一页 tags，数一下能匹配版本正则的比例。

**早期版本可能不符合现在的规律。** ripgrep 11.x 的 Windows zip 是平铺的，12.0.0 之后才有外层目录；投到 `strip_top` 上就是「11.x 解出一个空目录」。如果工具历史很长，要么在 provider 里按版本分支，要么在 spec 里声明一个最低支持版本。

**校验文件的格式不止一种。** ripgrep 的 `.sha256` 是 Windows CertUtil 的输出（`SHA256 hash of ...:` + 单独一行的 hex + 尾巴），现有的 `shasums_file` 和 `sha256_file` 都解析不了。遇到这种情况优先改用 `api_digest`（release payload 里自带），没有就写 `none`，不要为它改 `http.py` 的解析器——除非你确定以后还有别的工具也用这个格式。

## 验证包结构不必下载整个包

大包（JDK 有 205MB）不用下完：

- **zip**：用 Range 请求读最后几百 KB，解析中央目录里的文件名。
- **tar.gz**：读头几兆解压，`tarfile.open(..., errorlevel=0)` 容错，能扫出前面几百个成员名。

两条都能确认顶层目录名、二进制位置和是否带 Unix 权限位。写成一个临时脚本跑一次就行，不用提交。

## 已知要避开的坑

- macOS 的 JDK 是 `Contents/Home/bin/java`，不是 `bin/java`。
- Adoptium 的 `openjdk_version` 四段和三段混用，用 `semver`。
- 独立版 Bun 只有 `bun.exe`，没有 `bunx`。
- 顶层目录名经常山寨：Go 的包顶层就叫 `go`，bun 的叫 `bun-windows-x64`。
- GitHub API 未登录 60 次/小时，分页拉取时别翻到底才发现 403。
- `per_page=100` 的 URL 里包含 `page=1` 子串，测试桩别用 `in`。
