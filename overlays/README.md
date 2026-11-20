# Mentara Overlay Layers

Each subdirectory here represents an independent overlay layer stacked on top of
the original Mental Omega game directory. The shipped profiles stack them in
this order (bottom to top):

```text
Mental Omega 3.3.6 game directory   (read-only)
└─ overlays/base     fixes and adjustments to MO itself; stock Ares 3.0 only
   └─ overlays/phobos   Phobos engine fixes and modernization on the fixed game
```

`overlays/base` must keep working on its own (`just launch base`), so it holds
no Phobos keys, DLLs, or assets. Anything that needs `Phobos.dll` belongs in
`overlays/phobos`, which may assume the base fixes are present beneath it.

## Included Layers

- `overlays/base/`: Data fixes for Mental Omega 3.3.6 that need only the stock
  Ares 3.0 engine. Every fix was found by auditing the decrypted MO data and
  is documented next to the change:
  - **`expandmo99.mix/aimo.patch.ini`** (skirmish AI): MO defines four AI IDs
    twice with different contents, and the engine merges the copies key by key,
    so one of the teams sharing each ID got the other's units or script:
    - TaskForce `0ACDD81CB-G`: "4 Robots Water" vs "2 Robots" (Allied robot
      water team vs follow team).
    - ScriptType `0C31EA4CB-G`: the 7-action "Tanks vs Structures Nuclear
      Path" vs the 4-action "Quetzal vs Structures" merged into a hybrid.
    - TeamType `09B5712CB-G`: the "Robot Tanks Water 2" attack team vs the
      "Robot Tanks Defense 1" base-defence team.
    - TaskForce `SOVNTF02-G`: "Latin T2 Hunt" (Jaguars + Borillos) vs
      "Chinese T2 Hunt" (Qilins + Armadillos), so one country was asked to
      build units it cannot build.
    - The second definition of each moves to a fresh `MNT*-G` ID wired to the
      right team or trigger.
    - TeamType `FOETT176LB-G` was referenced by the "Last Bastion - Condor Oil
      Defense" trigger but never written, so Last Bastion never defended its
      oil derricks from the air; it is added using the existing "2 Condor"
      task force.
  - Exact duplicates that change nothing (`FOETF055-G`, `FOETF117-G`,
    `ULTITF60-G`, art `[GAOREFBB]`) are left alone.
- `overlays/phobos/`: Upstream **Phobos `v0.5-alpha2`** (`Phobos.dll`,
  bundled `Syringe.exe` / SyringeEx `0.1.0.2`, `gamemd.edb`,
  `Syringe.LICENSE.txt`, and `Phobos.pdb` which is excluded from Git via
  `*.pdb` in `.gitignore`), organized cleanly into categorized Westwood MIX
  containers and declarative `.patch.ini` files (zero loose asset clutter in
  the overlay root):
  - **`ecachephobos.mix/`** (auto-loaded via `ECACHE*.MIX` — custom modern HUD
    visual assets):
    - `phdigit.shp` + `phdigit.pal` / `phdigcy.pal`: Condensed `4×6` modernist
      micro-HUD telemetry numerals with directional drop-shadow (no heavy retro
      black borders) for hover unit/building HP and factory progress displays.
    - `phselinf.shp` + `phselunt.shp` + `phsel.pal`: Pure-light translucent
      holographic isometric selection rings (`EnableSelectBox=true`, zero black
      outline) with segmented corner tactical brackets and dashed vertical
      altitude drop-lines for aircraft and jumpjets.
    - Every SHP in this layer is RLE-zero data flagged as compression 3,
      the only RLE flag MO's own art uses and the one Phobos requires for
      select-box shapes (frames flagged 2 can draw like an AlphaImage).
    - `sws_{all,sov,eps,foe}_{top,mid,bot,on,off}.pcx`: 24-bit full-color
      architectural dark carbon-glass SuperWeapon Sidebar docks (`68×52`
      center, `68×10` chamfered caps, `12×40` slim chevron pull-tabs) styled
      for Allies, Soviet, Epsilon, and Foehn.
  - **`elocalphobos.mix/`** (auto-loaded via `ELOCAL*.MIX` — localization):
    - `stringtable50.csf`: Native Chinese CSF labels for Phobos HUD counters,
      tooltips, game clock (`TXT_GAMETIME`), and hotkey names/descriptions.
  - **`expandmo99.mix/`** (highest-priority `EXPANDMO%02d.MIX` overrides &
    config patches):
    - `place.shp`: Modern translucent holographic building placement grid
      (emerald-mint buildable pads with corner brackets, ice-cyan active
      reticle, coral-crimson blocked pads with isometric `×` cross, and all 16
      sloped terrain cells modernized pixel-accurately from base MO).
    - `pipbrd.shp`: Modern chamfered dark-carbon unit/infantry healthbar
      capsules with subtle quarter-ticks (replacing 1998 bright-grey checkered
      healthbar stripes).
    - `uimd.patch.ini`: Hides empty loading-screen spawn dots, speeds up smooth
      credit rolling (`MaxStep=500`), configures aligned harvester & power delta
      counters (`75%`/`100%` usage thresholds), sidebar `ProducingProgress` LED
      strips, slim `68×52` collapsible `SuperWeaponSidebar`, centered pause menu
      background, and anchored 340px extended tooltips with native CSF labels.
    - `rulesmo.patch.ini`: Enables modern RTS controls & QoL (building queues,
      auto-tab factory switching, building type-select, `AttackMove.Aggressive`
      & `AttackMove.UpdateTarget`, `ApproachTarget.StopWhenInRange`,
      `HarvesterScanAfterUnload`, `ExtendedAircraftMissions`,
      `NoTurret.TrackTarget`, `JumpjetClimb*`, `RecountBurst`,
      `TypeSelectUseIFVMode`, fast transport/bunker/amphibious boarding,
      `SortCameoByName`), performance & fixes (`DistributeTargetingFrame`,
      `ShakeIsLocal`, fixed blitters/lighting/targeting), modern visuals
      (`JumpjetTilt` flight banking, `JumpjetLevelLightMultiplier`,
      `NoAlphaImageOnBuildup`, translucent placement previews & holographic
      grid, ice-cyan blinking timers & airstrike laser lines, floating income,
      dynamic shadows & wakes, `SelectBox` rings, SHP digital displays with
      disguise protection), faction carbon-glass tooltips & counter themes, and
      `LowSelectionPriority` on all 10 harvester types. Opt-in Phobos fixes
      for vanilla bugs: `DisableOveroptimizationInTargeting` (units no longer
      settle for the first target in partial range),
      `AllowWeaponSelectAgainstWalls` (Secondary used on walls the Primary
      cannot hurt), `[AI] EnablePowerSurplus` (AI honours MO's
      `PowerSurplus=50`), and light-flash/combat-light effects that follow the
      player's detail level and `HideLightFlashEffects` toggle. Combat alerts
      use unit voices only (`CombatAlert.UseEVA=false`), because MO has no
      `EVA_UnitsInCombat`.
    - Several of these keys change gameplay (attack-move, burst recount,
      targeting, boarding, AI power), so online games need every player on
      the same profile.
  - **`expandmo96.mix/`** (per-side nested `sidec0{1md,2md,3,3md,4,4md}.mix/`):
    - `tab0{0..3}pp.shp`: Ultra-slim 3px borderless hairline glowing LED
      production progress strips rendered in each faction's native
      `sidebar.pal`.
  - **`RA2MO.patch.ini`**: Enables player-side `[Phobos]` UX toggles (crisp
    carbon-glass tooltips, `EnableSelectBox`, smart selection/deploy filtering,
    IFV mode type-select, placement preview, designator/enhancer range rings,
    SHP digital displays, power delta & harvester counters, game clock,
    centered subtitle board, adaptive real-time timers, mission start saves).
  - **`Resources/`**:
    - `ClientDefinitions.patch.ini`: Migrates `MentalOmegaClient.exe` to
      SyringeEx `--args="..."` launch syntax.
    - `KeyboardCommands.patch.ini`: Exposes Phobos hotkeys in the client's
      graphical Hotkey configuration window, including the ten super weapon
      sidebar slots `FireTacticalSW1`-`10` (unbound by default). The
      developer-only `Display Damage Numbers` command is not listed because
      MO sets `DebugKeysEnabled=no`.
    - `OptionsWindow.patch.ini`: Hides MO's optional `savefixmo.dll`
      ("存档功能修正"). It hooks seven of the same save/load addresses as
      Phobos and writes its own block into the save stream, so the two must
      not load together. Phobos covers its `BuildOffAlly`-after-load fix, but
      not its map-lighting-after-load fix; the `base` profile keeps the
      option.
  - Version notes (checked 2026-11-21): `v0.5-alpha2` (2026-10-10) is the
    newest published Phobos build; the latest stable `v0.4.0.2` predates the
    SyringeEx requirement, and nightlies must not be shipped. Phobos detects
    MO's stock Ares 3.0 (`20.333.289`) by PE timestamp and enables its full
    Ares compatibility set, so Ares 3.0p1 is not required.
    `-HideVersionWarning=` must match the Phobos `FileVersion` exactly, so
    update it in `ClientDefinitions.patch.ini` and the `syringe` profile with
    every Phobos upgrade. Saves are tied to the Phobos version line, and
    pre-Phobos saves are hidden.
  - Source: https://github.com/Phobos-developers/Phobos/releases/tag/v0.5-alpha2

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

A section that appears more than once in the target file (MO's `aimo.ini`
has several) is edited in every occurrence: `Key=Value` rewrites each `Key`
line, `!Key` removes all of them, `+=Value` numbers past the highest index
across all copies, and `[-Section]` deletes every copy. The result is the
same whichever duplicate the engine reads, and `[-X]` followed by `[X]`
replaces a duplicated definition with a single clean one.

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
