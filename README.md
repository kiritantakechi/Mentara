# Mentara

跨平台（Linux & Windows 对等架构）Mental Omega 虚拟叠层启动器，基于 `just`、`uv` 与 Python 3.15 工具链构建。

Mentara 在启动游戏时自动维护一个与原版游戏目录解耦的虚拟工作目录，将只读的原游戏目录、多个有序自定义叠层（INI、DLL、资源包等）与独立的可写状态层合成为统一视图：

- **原文件零污染**：游戏本体目录与自定义叠层目录均保持只读干净状态。
- **文件级 + 文本条目级 + MIX 容器级正交叠层**：
  - 整文件覆盖（`.dll`、`.mix`、`.ini`）、文本级补丁与 MIX 容器级解密合成职责完全正交，可跨多层按序组合。
  - **`<stem>.patch.{ini,map,yrm,mpr,cfg,inj}`（INI / 地图 / 键值级）**：直接由后缀确定目标格式（如 `ClientDefinitions.patch.ini` -> `ClientDefinitions.ini`、`c_aberration.patch.map` -> `c_aberration.map`、`aqrit.patch.cfg` -> `aqrit.cfg`、`Ares.dll.patch.inj` -> `Ares.dll.inj`）；支持分节与无节顶层 `Key=Value` 原地修改/新增（保留等号对齐）、`!Key` 删除键、`[-Section]` 删除整节、`+=Value` 自动按当前节最大数字键 `+1` 追加，完整保留注释与 CRLF 换行；目标文件中重复出现的同名节（如 MO `aimo.ini`）会在每一处同步修改/删除，结果与引擎读取哪一份重复键无关。
  - **`<target>.patch.toml`（通用明文行/块级）**：`[[text]]` 对称操作集（`replace`、`insert_before` / `insert_after`、`prepend` / `append`、`delete_lines`），适用于 `.config`、`.xml`、`.edb`、`.txt` 等任意明文。
  - **`<archive>.mix/`、`<stem>.patch.mix` 与叠层加密 `.mix` 自动解密（MIX 容器级引擎）**：
    - 内置对称六级 MIX 解密与净化引擎（`S1` 标准包、`S2` MVLoader `MVMXV1` 分块 AES-256-GCM + HKDF-SHA256 + zlib 并支持从 `MVLoader.dll` PE32 动态提取密钥、`S2b` CryptoRuntime `0x0004FFFF` RC4-sub + MT19937 流加密包、`S3` Westwood RSA-320 + Blowfish-ECB、`S4` 防解包 `0xFFFFFFFF` 哨兵 / 伪造尺寸 / 加权区间调度 DP 重叠诱饵剔除与孤立 XCC LMD 雕刻、`S5a` 移位头、`S5b` 坏计数恢复），自动启用 OpenSSL `libcrypto` 硬件加速并零依赖回退至纯 Python。
    - 自动识别并跳过伪装为 `.mix` 的 Windows PE DLL（`MZ` + `PE\x00\x00`），避免误损扩展二进制。
    - 支持任意深度的嵌套 `.mix` 递归解密与容器级修改（如 `ra2md.mix/localmd.mix/rulesmd.patch.ini`、`expandmo99.mix/rulesmo.patch.ini`、`<stem>.patch.mix`），严格按自底向上叠层顺序执行，并通过内容指纹缓存（`runtime_dir/mix-cache`）避免重复解密大体积归档。
    - 可在 `mentara.toml` 中通过 `[mix]`（全局或按 Profile 覆盖）配置 `decrypt = "layers" | "all" | "patched"`（默认 `"layers"` 自动解密所有叠层中的加密/防解包 `.mix` 及被补丁的底层 `.mix`）与可选 `mvmx_secret`。
- **Linux 与 Windows 对称设计**：
  - `[linux]` 与 `[windows]` 采用完全一致的 `PlatformConfig` 结构（`backend`、`runtime_dir`、`state_dir`、`runner`），同一份 `mentara.toml` 与 Profile 可在双平台直接运行。
  - **Linux**：默认使用 `fuse-overlayfs` 零复制联合挂载，自动通过 `.wh.` 白名单隐藏已消费的 `.patch.*` / `.patch.mix` 源文件以与 Windows 保持完全一致的虚拟目录视图，挂载点与状态层分别位于 `$XDG_CACHE_HOME/mentara/runtime` 与 `$XDG_STATE_HOME/mentara`。
  - **Windows**：默认使用 `symlink` 影子目录树（无开发者模式权限时自动回退至同卷 NTFS 硬链接 `os.link`，`.ini`/`.cfg`/存档隔离复制并在退出时回写），直接原生启动目标 `.exe`，挂载点与状态层位于 `%LOCALAPPDATA%\mentara`。
- **通用命令链解析与健康诊断 (`doctor`)**：Runner 与 `doctor` 通过 `--` 分隔符统一解析任意包装器链（如 `gamescope ... -- umu-run`），并校验基础目录、叠层目录、后端工具、目标可执行文件、大小写冲突以及全部文本补丁与 MIX 解密合成任务。

## 快速开始

在 `Mentara/` 目录下（Linux `bash` 与 Windows `PowerShell` 通用）：

```bash
just                            # 查看所有 just 任务
just doctor                     # 检查当前平台环境、核心游戏文件与叠层配置
just profiles                   # 列出所有已配置 Profile 及当前平台后端
just dry-run                    # 预览虚拟目录挂载方案与最终启动命令
just launch                     # 自动挂载 -> 启动游戏 -> 退出自动卸载
just mount                      # 手动挂载虚拟目录
just unmount                    # 手动卸载虚拟目录
just clean                      # 清理指定 Profile 的持久化运行状态层
just inspect                    # 查看叠层文件、补丁链或通过 --render 预览合成后文本
```

## 平台与叠层配置 (`mentara.toml`)

```toml
base_dir = ".."
default_profile = "default"

[linux]
backend = "fuse-overlayfs"

[linux.runner]
command = ["gamescope", "-W", "2560", "-H", "1440", "-w", "1920", "-h", "1080", "-f", "--", "umu-run"]
executable = "MentalOmegaClient.exe"
env = { WINEDLLOVERRIDES = "ddraw=n,b" }

[windows]
backend = "symlink"

[windows.runner]
command = []
executable = "MentalOmegaClient.exe"

# 叠层自底向上：游戏目录 -> overlays/base（MO 自身修复，仅需 Ares）
# -> overlays/phobos（基于火卫一的修复与现代化）
[profiles.default]
layers = ["overlays/base", "overlays/phobos"]
persist_state = true

[profiles.base]
layers = ["overlays/base"]
persist_state = true
```

## 开发与质量门禁

```bash
just sync       # 安装并同步全部依赖组
just fmt        # ruff format
just check      # fmt-check + ruff check + ty check + pytest
just cov        # 带覆盖率运行测试
just build      # 通过 uv_build 构建发布包
just assets     # 由 assets/ 构建叠层中的生成文件；just assets --check 只检查是否过期
```

## 目录结构

```text
Mentara/
├── src/mentara/   启动器、叠层/补丁/MIX 引擎，以及通用格式编解码（png、pal、shp、csf）与资源构建器
├── assets/        可编辑的资源源文件，目录结构与 overlays/ 一一对应
├── overlays/      叠层本体：手写补丁、上游二进制与由 assets/ 构建出的文件
└── tests/
```

`mentara assets` 按后缀把 `assets/<路径>` 编译到 `overlays/<路径>`（可在
`mentara.toml` 的 `[assets]` 中改 `source`/`output`），不依赖任何特定文件名：

| 源文件 | 生成 | 内容 |
|---|---|---|
| `<名>.csf.toml` | `<名>.csf` | `[strings]` 表：标签 = "文本" |
| `<名>.pal.toml` | `<名>.pal` | `colours = ["#RRGGBB", ...]`，按调色板索引排列 |
| `<名>.shp.toml` | `<名>.shp` | `sheet`（同目录索引色 PNG）按 `frame = [宽, 高]` 从左到右、从上到下切帧 |
| `<名>.dll/` | `<名>.dll` | Syringe 钩子 DLL 的 C 源码，用 clang + lld 构建（无 C 运行库） |

其余文件（如 PNG 帧图）是这些源文件的输入。生成文件随仓库提交，玩家无需工具链；
契约测试会在源文件改动而未重新构建时失败。
