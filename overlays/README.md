# Mentara Overlay Layers

Each subdirectory here represents an independent overlay layer stacked on top of
the original Mental Omega game directory.

## Included Layers

- `overlays/phobos/`: Upstream **Phobos `v0.5-alpha2`** (`Phobos.dll`,
  bundled `Syringe.exe` / SyringeEx `0.1.0.2`, `gamemd.edb`,
  `Syringe.LICENSE.txt`, and `Phobos.pdb` which is excluded from Git via
  `*.pdb` in `.gitignore`), plus the text-level patch
  `Resources/ClientDefinitions.ini.patch.ini` which modifies only the 3
  `[Settings]` keys needed for SyringeEx's `--args="..."` launch syntax.
  - Source: https://github.com/Phobos-developers/Phobos/releases/tag/v0.5-alpha2
  - Stacked *below* `overlays/base` so local overrides in `overlays/base`
    always take precedence.
- `overlays/base/`: Your local custom INI / DLL overrides and `.patch.ini` /
  `.patch.toml` text patches.

## Text-Level Patching (`.patch.ini` & `.patch.toml`)

Instead of copying an entire INI or config file just to change a few entries,
drop a `<target>.patch.ini` or `<target>.patch.toml` at the same relative path:

### 1. `<target>.patch.ini` (Native Westwood INI Patch)

For example, `overlays/phobos/Resources/ClientDefinitions.ini.patch.ini`:

```ini
; Modify or add keys in [Settings]
[Settings]
GameExecutableNames=Syringe.exe
GameLauncherExecutableName=
ExtraCommandLineParams=gamemd.exe --args="-SPAWN -CD -SPEEDCONTROL -LOG -AFFINITY:1048575"

; Remove a key with !Key or -Key
!ForbiddenFiles

; Auto-numbered Westwood list append (+=Value appends at max_index + 1)
[Animations]
+=NEW_PHOBOS_ANIM

; Remove an entire section with [-SectionName]
[-DeprecatedSection]
```

### 2. `<target>.patch.toml` (Plaintext Line & Block Patch)

Works on any plaintext file (`.cfg`, `.config`, `.txt`, `.ini`):

```toml
[[text]]
op = "replace"          # "replace" | "insert_after" | "insert_before" | "delete_lines" | "append" | "prepend"
target = "Renderer=auto"
replacement = "Renderer=opengl"

[[text]]
op = "insert_after"
anchor = "[Video]"
content = "; Managed by Mentara"
```

## How Layering Works

Configure ordered layers in `mentara.toml`:

```toml
[profiles.modded]
layers = ["overlays/base", "overlays/phobos", "overlays/my-balance"]
```

Layers are applied from left to right on top of `base_dir`:
- Later layers override earlier layers.
- All layers override the base Mental Omega directory.
- Runtime writes (saves, logs, `RA2MO.ini` changes) go into the isolated
  per-profile state directory (`$XDG_STATE_HOME/mentara/<profile>/upper`),
  leaving both the original game directory and overlay layers untouched.

## Typical Layer Contents

```text
overlays/<layer-name>/
├── ddraw.dll                     # Custom renderer DLL override
├── ddraw.ini                     # Custom renderer config
├── Phobos.dll                    # Extra Syringe-injected DLL
├── rulesmo.ini                   # Loose INI override (note ForbiddenFiles!)
├── INI/
│   └── Game Options/...
└── Resources/
    └── ClientDefinitions.ini     # Override if loosening ForbiddenFiles
```

> Note: `MentalOmegaClient.exe` checks `ForbiddenFiles` in
> `Resources/ClientDefinitions.ini` (`rulesmo.ini,artmo.ini,soundmo.ini,aimo.ini`).
> Run `just doctor` to catch case collisions and `ForbiddenFiles` conflicts early.
