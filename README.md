# Mentara

Mental Omega 虚拟叠层启动器，基于 `just`、`uv` 与 Python 3.15 工具链构建。

Mentara 在启动游戏时自动维护一个与原版游戏目录解耦的虚拟工作目录，将只读的原游戏目录、多个有序自定义叠层（INI、DLL、资源包等）与独立的可写状态层合成为统一视图，从而做到：

- **原文件零污染**：游戏本体目录与自定义叠层目录均保持只读干净状态。
- **INI / DLL 透明读取**：`MentalOmegaClient.exe`、`Syringe.exe`、`gamemd.exe` 以及 Ares/Phobos 等 DLL 在虚拟目录中按叠层优先级无缝读取。
- **双虚拟目录后端**：
  - `fuse-overlayfs`（默认）：基于 Linux FUSE 的零复制联合挂载，对 Wine / Proton / `umu-run` 与 DLL 加载器最透明，退出自动卸载。
  - `symlink`：不依赖 FUSE 的影子目录树，大体积 `.mix` 使用符号链接、可写 `.ini`/`.cfg`/存档自动隔离复制，并在卸载时将变更回写到独立状态层。
- **通用可配置 Runner**：支持 `umu-run` / Proton、`wine` 或任意自定义启动命令、环境变量（`WINEPREFIX`、`PROTONPATH`、`WINEDLLOVERRIDES`）与目标入口（`MentalOmegaClient.exe` / `Syringe.exe`）。
- **Mental Omega 专项诊断 (`doctor`)**：检查必需核心文件、Linux/Windows 大小写冲突（如 `RA2MO.ini` vs `ra2mo.ini`），以及 `Resources/ClientDefinitions.ini` 的 `ForbiddenFiles` 冲突提示。

## 快速开始

在 `Mentara/` 目录下：

```bash
# 查看所有 just 任务
just

# 检查运行环境、核心游戏文件与叠层配置
just doctor

# 列出所有已配置 Profile
just profiles

# 预览虚拟目录挂载方案与最终启动命令（不实际启动）
just dry-run

# 启动默认 Profile（自动挂载 -> 启动游戏 -> 退出自动卸载）
just launch

# 使用 Syringe.exe 直连 Profile 或切换到 symlink 后端
just launch syringe
just launch default --backend symlink
```

## 叠层目录与多 Profile

在 `mentara.toml` 中按从低到高的优先级声明叠层：

```toml
[profiles.modded]
description = "平衡性补丁 + 自定义 DLL"
layers = ["overlays/base", "overlays/phobos", "overlays/balance"]
persist_state = true

[profiles.modded.runner]
command = ["umu-run"]
executable = "MentalOmegaClient.exe"
env = { WINEDLLOVERRIDES = "ddraw=n,b;Phobos=n,b" }
```

常用叠层管理命令：

```bash
# 创建新的叠层目录
just init-layer phobos

# 查看哪些 INI / DLL 被覆盖及其遮蔽来源
just inspect-ini-dll

# 手动挂载/卸载虚拟目录以便调试检查
just mount
just unmount
```

> 虚拟挂载点默认位于 `$XDG_RUNTIME_DIR/mentara/<profile>/merged`，可写持久化层默认位于 `$XDG_STATE_HOME/mentara/<profile>/upper`，均处于原游戏目录之外，避免 `Mentara/` 位于游戏根目录内造成嵌套递归。

## 开发与质量门禁

```bash
just sync       # 安装并同步全部依赖组
just fmt        # ruff format
just check      # fmt-check + ruff check + ty check + pytest
just cov        # 带覆盖率运行测试
just build      # 通过 uv_build 构建发布包
```
