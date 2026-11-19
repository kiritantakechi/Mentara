# Mentara

跨平台（Linux & Windows 对等架构）Mental Omega 虚拟叠层启动器，基于 `just`、`uv` 与 Python 3.15 工具链构建。

Mentara 在启动游戏时自动维护一个与原版游戏目录解耦的虚拟工作目录，将只读的原游戏目录、多个有序自定义叠层（INI、DLL、资源包等）与独立的可写状态层合成为统一视图：

- **原文件零污染**：游戏本体目录与自定义叠层目录均保持只读干净状态。
- **文件级 + 文本条目级 + MIX 容器级正交叠层**：
  - 整文件覆盖（`.dll`、`.mix`、`.ini`）、文本级补丁与 MIX 容器级解密合成职责完全正交，可跨多层按序组合。
  - **`<stem>.patch.{ini,map,yrm,mpr,cfg,inj}`（INI / 地图 / 键值级）**：直接由后缀确定目标格式（如 `ClientDefinitions.patch.ini` -> `ClientDefinitions.ini`、`c_aberration.patch.map` -> `c_aberration.map`、`aqrit.patch.cfg` -> `aqrit.cfg`、`Ares.dll.patch.inj` -> `Ares.dll.inj`）；支持分节与无节顶层 `Key=Value` 原地修改/新增（保留等号对齐）、`!Key` 删除键、`[-Section]` 删除整节、`+=Value` 自动按当前节最大数字键 `+1` 追加，完整保留注释与 CRLF 换行。
  - **`<target>.patch.toml`（通用明文行/块级）**：`[[text]]` 对称操作集（`replace`、`insert_before` / `insert_after`、`prepend` / `append`、`delete_lines`），适用于 `.config`、`.xml`、`.edb`、`.txt` 等任意明文。
  - **`<archive>.mix/` 与 `<stem>.patch.mix`（MIX 容器级解密与混合）**：内置多级 MIX 解密与净化引擎（支持 S1 标准包、S2b CryptoRuntime RC4+MT19937 流加密包、S3 Westwood RSA-320 + Blowfish-ECB 加密包、S4 防解包 `0xFFFFFFFF` 哨兵/伪造尺寸/加权区间调度 DP 重叠诱饵剔除与孤立 XCC 文件名表雕刻、S5 坏计数索引恢复）。在叠层中创建 `<archive>.mix/` 目录（例如 `overlays/phobos/expandmo99.mix/rulesmo.patch.ini` 与 `uimd.patch.ini`）或放置 `<stem>.patch.mix`，即可直接对 `.mix` 包内任意条目打文本补丁或注入替换文件，并在虚拟工作区自动合成为标准未加密 `.mix` 归档，无需解包污染根目录。
- **Linux 与 Windows 对称设计**：
  - `[linux]` 与 `[windows]` 采用完全一致的 `PlatformConfig` 结构（`backend`、`runtime_dir`、`state_dir`、`runner`），同一份 `mentara.toml` 与 Profile 可在双平台直接运行。
  - **Linux**：默认使用 `fuse-overlayfs` 零复制联合挂载，通过 `gamescope ... -- umu-run` 链式启动，挂载点与状态层分别位于 `$XDG_CACHE_HOME/mentara/runtime` 与 `$XDG_STATE_HOME/mentara`。
  - **Windows**：默认使用 `symlink` 影子目录树（无开发者模式权限时自动回退至同卷 NTFS 硬链接 `os.link`，`.ini`/`.cfg`/存档隔离复制并在退出时回写），直接原生启动目标 `.exe`，挂载点与状态层位于 `%LOCALAPPDATA%\mentara`。
- **通用命令链解析**：Runner 与 `doctor` 通过 `--` 分隔符统一解析任意包装器链（如 `gamescope ... -- umu-run`）中的每个可执行文件，无需针对特定工具打补丁。
- **Mental Omega 专项诊断 (`doctor`)**：检查核心文件、大小写冲突（如 `RA2MO.ini` vs `ra2mo.ini`）、`ForbiddenFiles` 冲突及 `SyringeEx` 的 `ClientDefinitions.ini` 语法迁移。

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

[profiles.default]
layers = ["overlays/phobos", "overlays/base"]
persist_state = true
```

## 开发与质量门禁

```bash
just sync       # 安装并同步全部依赖组
just fmt        # ruff format
just check      # fmt-check + ruff check + ty check + pytest
just cov        # 带覆盖率运行测试
just build      # 通过 uv_build 构建发布包
```
