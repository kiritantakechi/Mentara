# Mentara

跨平台（Linux & Windows 对等架构）Mental Omega 虚拟叠层启动器，基于 `just`、`uv` 与 Python 3.15 工具链构建。

Mentara 在启动游戏时自动维护一个与原版游戏目录解耦的虚拟工作目录，将只读的原游戏目录、多个有序自定义叠层（INI、DLL、资源包等）与独立的可写状态层合成为统一视图：

- **原文件零污染**：游戏本体目录与自定义叠层目录均保持只读干净状态。
- **INI / DLL 透明读取**：`MentalOmegaClient.exe`、`Syringe.exe`、`gamemd.exe` 以及 Ares/Phobos 等 DLL 在虚拟目录中按叠层优先级无缝读取。
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
just launch syringe             # 使用 Syringe.exe 直连 Profile
just launch default --backend symlink  # 临时切换虚拟目录后端
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
