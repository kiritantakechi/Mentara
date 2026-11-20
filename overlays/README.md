# Mentara Overlay Layers

Each subdirectory here represents an independent overlay layer stacked on top of
the original Mental Omega game directory. The shipped profiles stack them in
this order (bottom to top):

```text
Mental Omega 3.3.6 game directory   (read-only)
└─ overlays/base     fixes and adjustments to MO itself; Ares 3.0p1, no Phobos
   └─ overlays/phobos   Phobos engine fixes and modernization on the fixed game
```

`overlays/base` must keep working on its own (`just launch base`), so it holds
no Phobos keys, DLLs, or assets. Anything that needs `Phobos.dll` belongs in
`overlays/phobos`, which may assume the base fixes are present beneath it.

## Included Layers

- `overlays/base/`: Fixes for Mental Omega 3.3.6 that need only Ares. Every
  fix was found by auditing the decrypted MO data or the running engine and
  is documented next to the change:
  - **`Ares.dll` + `Ares.dll.inj`**: Ares 3.0p1 (`21.352.1218`, the newest
    Ares release) replaces MO's Ares 3.0. It is the official backward
    compatible service release (crash, super weapon timer, cloning,
    tunnel and harvester-docking fixes; 3.0 saves still load), and Phobos
    detects it by PE timestamp. Ares versions must match for online play,
    so mixed lobbies need every player on the same profile. A contract
    test checks the `.inj` schedules every hook the DLL exports.
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
  - **`MentaraFixes.dll`** (Syringe hook DLL built from
    `assets/base/MentaraFixes.dll/` by `just assets`; Syringe injects it
    next to Ares): campaigns crashed under
    Wine with stock MO (exit `C0000005` at `0x00529A14`). The CnCNet spawner
    routes every `-SPAWN` game through the scenario reader that loads the
    multiplayer `[Header]` without resetting it first; campaign maps have no
    `[Header]`, so the start-point loop ran for whatever the uninitialized
    count held (leftover UTF-16 text under Wine, about 7.3 million) and ran
    off the scenario object. The hook skips that block in campaigns at
    `0x689EB0`, exactly like Phobos's `ScenarioClass_ReadMap_SkipHeaderInCampaign`,
    so the Ares-only and Phobos stacks behave alike and loading both is
    harmless (Ares 3.0p1 alone does not fix it). Syringe walks hook tables
    with a 16-byte stride, so its `syringe.h` aligns each entry to 16.
  - **`expandmo99.mix/artmo.patch.ini`**: seven civilian buildings (`CAWHSE`,
    `CAJHUT`, `CANHSE01/02`, `CAPRSNF`, `CASLUMA`, `CABRKK`) name a `cargo`
    palette that no MO archive ships (all 41 other custom palettes ship every
    theater variant). The engine already falls back to the theater palette,
    so the dangling `Palette=cargo` is dropped without changing their look.
  - **`expandmo99.mix/uimd.patch.ini`**: `[UISettings] CampaignButton=show` is
    not an Ares value (`default|disable|hide|message|credits|sneakpeek`) and
    logged "Unrecognized UI action value" on every start; it is `default`.
- `overlays/phobos/`: Upstream **Phobos `v0.5-alpha2`** (`Phobos.dll`, SyringeEx
  `0.1.0.2` as `Syringe.exe`, `gamemd.edb`, and `Phobos.pdb`, kept out of Git)
  with declarative patches and a small set of generated assets.
  - **HUD design ("quiet, native")**: every Phobos addition should look like it
    shipped with MO. Readouts use MO's fonts and faction colours, appear on
    hover or selection rather than permanently, and share one colour system:
    green `118,236,140`, amber `248,208,96`, red `248,100,96`.
    - Credits strip: power surplus (left) and active/total harvesters (right)
      as bare numbers. Their labels are empty because the strip draws in the
      `Metal12` numeral font, which has no CJK glyphs (the old "电"/"矿"
      labels rendered as garbage). The harvester count keeps the side's
      `ToolTipColor`, like the credits figure beside it.
    - Selection: a thin ground ellipse per selected unit, tinted by health,
      with a brighter front arc so it reads as lying on the ground; no drop
      lines.
    - Hover readout: `current/max` health in a 3x5 pixel font sitting on
      the health bar (parallel to the diagonal bar on buildings), plus a
      light-blue production percentage beside your own factories.
    - Tooltips: anchored left of the sidebar, `name / $cost mm:ss ±power`.
      (The string loader strips trailing spaces, so values carry no labels
      where a separator would be needed.)
    - Messages stay in MO's top-left list (hover keeps them); the centred
      message board and its toggle button are off. The game clock reads
      `时间 mm:ss` like MO's own timers.
    - Super weapon sidebar on the left edge shows MO's own cameos without
      frame art; hotkeys `FireTacticalSW1`-`10` are bindable in the client.
  - **`expandmo50.mix/`**: a new `EXPANDMO%02d.MIX` archive for Phobos-only
    files. It must be an expansion archive: the engine parses CSF tables and
    rules right after the `EXPANDMO` archives load and finds `ECACHE*`/
    `ELOCAL*` archives only later, which once left every `PHOBOS:*` label
    missing and crashed missions on start (exit `C0000409`). Its number sits
    below MO's 94-99, so it can only add files. Everything in it is built by
    `just assets` from `assets/phobos/expandmo50.mix/`, where it is edited:
    - `phselinf.shp`, `phselunt.shp` + `phsel.pal`: the selection rings,
      three health frames each (sheets `phselinf.png`, `phselunt.png`).
    - `phdigit.shp` + `phdigit.pal` / `phdigcy.pal`: the 3x5 readout font
      in Phobos's 36-frame layout (sheet `phdigit.png`); the second
      palette tints factory progress light blue.
    - `stringtable50.csf`: Chinese labels and hotkey names
      (`stringtable50.csf.toml`).
  - **`expandmo99.mix/`** (replacements of MO's own files and config patches):
    - `place.shp` (translucent placement grid), `pipbrd.shp` (health bar frame).
    - `uimd.patch.ini`: loading screen, credits roll speed, the counters, the
      super weapon sidebar layout, production strips, tooltips.
    - `rulesmo.patch.ini`: the HUD above plus modern RTS controls and fixes:
      building queues, factory tab switching, building type-select,
      attack-move, `ApproachTarget.StopWhenInRange`, extended aircraft
      missions, turret tracking, burst recount, jumpjet climb/tilt, fast
      boarding, `SortCameoByName`, `DistributeTargetingFrame`, `ShakeIsLocal`,
      blitter/lighting/targeting fixes, floating income, shadows and wakes,
      combat alerts (unit voices only; MO has no `EVA_UnitsInCombat`), low box
      selection priority for all 10 harvesters, and the opt-in vanilla fixes
      `DisableOveroptimizationInTargeting`, `AllowWeaponSelectAgainstWalls`,
      `[AI] EnablePowerSurplus`, and detail-aware light flashes.
    - Several of these keys change gameplay, so online games need every player
      on the same profile.
  - **`expandmo96.mix/`**: `tab0{0..3}pp.shp` production progress strips in
    each faction's `sidebar.pal` (nested `sidec0*.mix`).
  - **`RA2MO.patch.ini`**: the player-side `[Phobos]` toggles behind the HUD.
  - **`Resources/`**:
    - `ClientDefinitions.patch.ini`: launches through SyringeEx `--args="..."`.
    - `KeyboardCommands.patch.ini`: Phobos hotkeys in the client's hotkey
      window (unbound super weapon slots; no developer-only commands).
    - `OptionsWindow.patch.ini`: hides MO's optional `savefixmo.dll`
      ("存档功能修正"), which hooks seven of the same save/load addresses as
      Phobos. Phobos covers its `BuildOffAlly`-after-load fix but not its
      map-lighting-after-load fix; the `base` profile keeps the option.
  - Version notes (checked 2026-11-21): `v0.5-alpha2` is the newest published
    Phobos build; nightlies must not be shipped. `-HideVersionWarning=` must
    match the Phobos `FileVersion` (a contract test checks it against
    `Phobos.dll`). Saves are tied to the Phobos version line, and pre-Phobos
    saves are hidden.
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
