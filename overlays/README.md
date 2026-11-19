# Mentara Overlay Layers

Each subdirectory here represents an independent overlay layer stacked on top of
the original Mental Omega game directory.

## Included Layers

- `overlays/phobos/`: Upstream **Phobos `v0.5-alpha2`** (`Phobos.dll`,
  bundled `Syringe.exe` / SyringeEx `0.1.0.2`, `gamemd.edb`,
  `Syringe.LICENSE.txt`, and `Phobos.pdb` which is excluded from Git via
  `*.pdb` in `.gitignore`), bespoke modern pixel-art SHP/PCX HUD assets,
  Chinese CSF localization (`stringtable50.csf`), and declarative
  `.patch.ini` / nested MIX container patches (`expandmo99.mix/`,
  `expandmo96.mix/`):
  - **Custom Modern HUD Assets**:
    - `phdigit.shp` + `phdigit.pal` / `phdigcy.pal`: Crisp 36-frame micro-HUD
      pixel numerals (emerald / amber / coral / cyber-cyan with 1px dark
      outline, zero solid black boxes) for hover unit/building HP and factory
      progress displays.
    - `phselinf.shp` + `phselunt.shp` + `phsel.pal`: Translucent 2:1 isometric
      chamfered octagonal ground selection rings (`EnableSelectBox=true`) with
      HP-colored cardinal brackets and dashed vertical altitude drop-lines for
      aircraft and jumpjets.
    - `sws_{all,sov,eps,foe}_{top,mid,bot,on,off}.pcx`: 24-bit full-color
      faction-matched C&C3-style left SuperWeapon Sidebar panels and
      collapsible toggle tabs for Allies, Soviet, Epsilon, and Foehn.
    - `expandmo96.mix/sidec0{1md,2md,3,3md,4,4md}.mix/tab0{0..3}pp.shp`:
      C&C Remastered-style glowing LED production progress bars drawn directly
      below each sidebar tab in each faction's native `sidebar.pal`.
    - `stringtable50.csf`: Native Chinese CSF labels for Phobos HUD counters,
      tooltips, game clock (`TXT_GAMETIME`), and hotkey names/descriptions
      (eliminating missing-glyph squares from unsupported Unicode emojis).
  - `RA2MO.patch.ini`: Enables `[Phobos]` crisp tooltip descriptions (with
    16-bit blur smear disabled), isometric `EnableSelectBox`, smart harvester
    selection/deployment filtering, IFV mode type-select, building placement
    preview, designator/enhancer range rings, SHP digital displays, power delta
    & harvester counters, elapsed game clock, translucent centered subtitle
    board, adaptive real-time timers, and mission start checkpoint saves.
  - `expandmo99.mix/uimd.patch.ini`: Enables fast smooth credit rolling
    (`MaxStep=500`), aligned harvester & power delta counters (with corrected
    `75%` / `100%` usage thresholds), sidebar `ProducingProgress` LED bars,
    C&C3-style collapsible `SuperWeaponSidebar`, centered pause menu
    background, and anchored 340px extended tooltips with native CSF labels.
  - `expandmo99.mix/rulesmo.patch.ini`: Enables building production queues,
    building type-select, auto-tab factory switching, fast transport/bunker
    boarding & unloading, crisp translucent placement previews (`50%`) over a
    soft grid (`75%`), floating `$` income/drain indicators, dynamic turret &
    altitude-scaled shadows, fixed voxel lighting & blitters, water wakes,
    off-screen combat voice alerts, `SelectBox` rings, SHP micro-HUD digital
    displays, faction-coordinated tooltip glass & counter palettes/offsets for
    all 4 Mental Omega factions, win/lose themes, and `LowSelectionPriority` on
    all 10 harvester types.
  - `Resources/ClientDefinitions.patch.ini`: Migrates `MentalOmegaClient.exe`
    to SyringeEx `--args="..."` launch syntax.
  - `Resources/KeyboardCommands.patch.ini`: Exposes Phobos hotkeys (Idle
    Harvester, Select Captured, Deselect 1/5, Toggle Digital Display, Toggle
    Designator Range, Toggle Super Weapon Sidebar, Toggle Center Message Board,
    Quicksave, Damage Numbers) in the client's graphical Hotkey configuration
    window.
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

## MIX Container Overlays & Automatic Decryption

Mentara decrypts, sanitizes, and mixes `.mix` archives across all six TS/RA2/YR
formats (`S1:standard`, `S2:mvmx` MVLoader AES-256-GCM + zlib with automatic
`MVLoader.dll` key extraction, `S2b:fw_crypto`, `S3:westwood`, `S4:sanitize`,
`S5a:shifted`, `S5b:count_recover`), including arbitrarily nested `.mix` archives:

- **Encrypted `.mix` directly in an overlay layer** (e.g.
  `overlays/mymod/expandmo95.mix`): under the default `[mix] decrypt = "layers"`
  policy, encrypted, obfuscated, or nested-encrypted `.mix` archives in any
  overlay layer are automatically decrypted into clean `S1:standard` archives
  (cached by content fingerprint in `runtime_dir/mix-cache`). Already-clean
  `S1:standard` archives and PE DLLs disguised as `.mix` stay zero-copy.
- **`<stem>.patch.mix`**: merges entries from an overlay `.mix` (plain or
  encrypted) onto the lower `<stem>.mix` by 32-bit MIX ID in strict layer order.
- **`<archive>.mix/` directory**: patches text entries (`rulesmo.patch.ini`),
  injects/replaces loose files (`extra.shp`), or descends into nested `.mix`
  archives (`ra2md.mix/localmd.mix/rulesmd.patch.ini`,
  `ra2md.mix/localmd.patch.mix`).

## Typical Layer Contents

```text
overlays/<layer-name>/
├── ddraw.dll                          # Custom renderer DLL override
├── ddraw.ini                          # Custom renderer config
├── Phobos.dll                         # Extra Syringe-injected DLL
├── expandmo92.mix                     # Standalone .mix (auto-decrypted if encrypted)
├── expandmo99.patch.mix               # Entry-level binary MIX merge
├── expandmo99.mix/
│   ├── rulesmo.patch.ini              # Text patch inside expandmo99.mix
│   └── uimd.patch.ini                 # Text patch inside expandmo99.mix
└── Resources/
    └── ClientDefinitions.patch.ini    # INI entry-level patch
```

> Note: `MentalOmegaClient.exe` checks `ForbiddenFiles` in
> `Resources/ClientDefinitions.ini` (`rulesmo.ini,artmo.ini,soundmo.ini,aimo.ini`).
> Patching `rulesmo.ini` inside `expandmo99.mix/` keeps the root directory clean
> of loose `rulesmo.ini` files. Run `just doctor` to validate all patches and
> MIX archives before launching.
