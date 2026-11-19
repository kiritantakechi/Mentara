# Mentara Overlay Layers

Each subdirectory here represents an independent overlay layer stacked on top of
the original Mental Omega game directory.

## Included Layers

- `overlays/phobos/`: Upstream **Phobos `v0.5-alpha2`** (`Phobos.dll`,
  bundled `Syringe.exe` / SyringeEx `0.1.0.2`, `gamemd.edb`,
  `Syringe.LICENSE.txt`, and `Phobos.pdb` which is excluded from Git via
  `*.pdb` in `.gitignore`), plus declarative `.patch.ini` files (including
  virtual MIX container patches under `expandmo99.mix/`) that modernize
  Mental Omega's UX, visuals, HUD, controls, and client launch:
  - `RA2MO.patch.ini`: Enables `[Phobos]` extended tooltip descriptions &
    blur, smart harvester selection/deployment filtering, IFV mode type-select,
    building placement preview, designator/enhancer range rings, floating
    digital displays, power delta & harvester counters, elapsed game clock,
    centered subtitle board, adaptive real-time timers, and automatic
    campaign mission start checkpoint saves.
  - `expandmo99.mix/uimd.patch.ini`: Patches `uimd.ini` directly inside
    `expandmo99.mix` (automatically decrypting/sanitizing the S4-protected
    base `expandmo99.mix` and mixing the patched entry back into the virtual
    `expandmo99.mix`) to enable fast smooth credit rolling (`MaxStep=500`),
    sidebar harvester & power delta counters, centered pause menu background
    on widescreen displays, and anchored 360px extended tooltips.
  - `expandmo99.mix/rulesmo.patch.ini`: Patches `rulesmo.ini` directly inside
    `expandmo99.mix` (avoiding loose root `rulesmo.ini` files and keeping
    `ClientDefinitions.ini` `ForbiddenFiles` intact) to enable building
    production queues, auto-tab switching when selecting factories, fast
    transport/bunker boarding & unloading, translucent building placement
    previews, floating `$` harvester/grinder income & drain numbers, dynamic
    turret & altitude-scaled aircraft shadows, fixed voxel lighting & RLE
    transparency blitters, water wakes for all locomotors, off-screen combat
    voice alerts, hover HP & factory progress digital displays,
    faction-specific in-game win/lose themes, and `LowSelectionPriority=true`
    on all 10 Mental Omega harvester types.
  - `Resources/ClientDefinitions.patch.ini`: Migrates `MentalOmegaClient.exe`
    to SyringeEx `--args="..."` launch syntax.
  - `Resources/KeyboardCommands.patch.ini`: Exposes Phobos hotkeys (Idle
    Harvester, Select Captured, Deselect 1/5, Toggle Digital Display, Toggle
    Designator Range, Toggle Center Message Board, Quicksave, Damage Numbers)
    in the client's graphical Hotkey configuration window.
  - `Resources/OptionsWindow.patch.ini`: Hides the legacy 2021 `savefixmo.dll`
    checkbox which is natively superseded by Phobos `v0.5-alpha2`.
  - Source: https://github.com/Phobos-developers/Phobos/releases/tag/v0.5-alpha2
- `overlays/base/`: Your local custom overrides, `<stem>.patch.*` text patches,
  and `<archive>.mix/` container overlays (stacked above `overlays/phobos`).

## Text-Level Patching

Instead of copying an entire config or map file just to change a few entries,
drop a patch file at the same relative path:

### 1. `<stem>.patch.{ini,map,yrm,mpr,cfg,inj}` (Native Westwood INI / Map / KV Patch)

Directly maps `<stem>.patch.<ext>` to `<stem>.<ext>`:
- `*.patch.ini` -> `*.ini` (INI configs & rules, e.g. `Resources/ClientDefinitions.patch.ini` -> `Resources/ClientDefinitions.ini`)
- `*.patch.map` -> `*.map` (Mental Omega campaign/challenge/skirmish maps, e.g. `MapsMO/Challenge/c_aberration.patch.map`)
- `*.patch.yrm` / `*.patch.mpr` -> `*.yrm` / `*.mpr` (YR / RA2 custom maps)
- `*.patch.cfg` -> `*.cfg` (flat key-value configs, e.g. `Resources/aqrit.patch.cfg`)
- `*.patch.inj` -> `*.inj` (Syringe hook definitions, e.g. `Ares.dll.patch.inj`)

For example, `overlays/phobos/Resources/ClientDefinitions.patch.ini`:

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
