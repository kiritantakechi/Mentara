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
  - Entries that name the wrong thing (fixes 6-8):
    - "Spy vs Foe Factory" (`SPYFOE03(B)-G`) targeted building 131171,
      a black fence, instead of 131771, the Foehn war factory (two
      digits swapped).
    - The Latin and Chinese garrison task forces `SOVNTF41/42-G` asked
      for the Russia-only Shock Trooper, so they never filled; both
      countries build the Tesla Trooper `SHK`.
    - Two Soviet triggers (`SOVTRI197/199-G`) built the Allied-only
      Dustdevil and held a team slot until it dissolved; they are off.
  - **`expandmo99.mix/rulesmo.patch.ini`**: the elite projectile of the
    Catastrophe, Centurion and Mammoth missiles kept vanilla's
    anti-air-only flag while every rookie form also hits the ground, so
    promotion took the ground attack away; it hits both.
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
    The same DLL fixes LAN and online games with a spectator, which crashed
    on load (`0x005D6C21`): the CnCNet client writes 90 as a spectator's
    spawn location, and the first pass that places preset start positions
    (`0x5D6BE0`, shared by every multiplayer game mode) used it unchecked
    as an index into the map's 8 start waypoints and into a 16-slot table,
    reading past a heap buffer (a crash whenever that read crossed into an
    unmapped page) and writing into `ScenarioClass`. The hook at
    `0x005D6C1D` skips any index the map does not have; the second pass
    then places that house as before (a spectator gets YR's observer cell),
    and preset positions of real players are untouched.
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
    hover or selection rather than permanently, and share one colour system
    taken from MO's own health pips (`pips.shp` frames 16-18 in
    `palette.pal`): green `0,255,0`, yellow `255,215,0`, red `255,0,0`,
    each with the pip's darker second tone where a shape needs depth. So
    the bar, the ring, the hover number and the power counter are one
    colour, and so are Phobos's floating `+$`/`-$` figures, which are
    hard-coded to the same pure green and red. (`palette.pal`, which the
    engine draws pips with, has no softer greens, so MO's pips cannot
    move toward any other tone; MO's icons stay untouched.) Sidebar
    chrome instead takes each side's own accent from its `sidebar.pal`.
    - Layers: overhead readouts (bars, numbers, the promotion badge) are
      UI and may draw over the world; anything on the ground (selection
      rings, the placement grid) is drawn flat in the depth buffer under
      units. An anim has a single layer and depth mode, so no anim mixes
      the two.
    - Credits strip: power surplus (left) and active/total harvesters (right)
      as bare numbers. Their labels are empty because the strip draws in the
      `Metal12` numeral font, which has no CJK glyphs (the old "电"/"矿"
      labels rendered as garbage). The harvester count keeps the side's
      `ToolTipColor`, like the credits figure beside it.
    - Selection: a thin ground ellipse per selected unit, tinted by health,
      with a brighter front arc so it reads as lying on the ground; no drop
      lines. The ring lies under its unit in the depth buffer, so it is
      sized to the hull: vehicles and aircraft whose body voxel sweeps past
      the standard ring take one of four larger rings (radius 30, 38, 46
      or 58 px), chosen from half the diagonal of the body's voxel bounds
      in MO 3.3.6. The 174 assignments are listed at the end of
      `rulesmo.patch.ini` with the rule that produced them.
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
    - Build tabs: while a factory works, the tab's bottom bezel holds an
      inset LED bar in the side's accent (Allied cyan, Soviet amber,
      Epsilon violet, Foehn teal), one pixel per progress step, lit across
      when the item is ready. Each side's bar is drawn for its own tab art,
      at the tab buttons' origin (no `Sidebar.ProducingProgress.Offset`).
    - Promotion: the unit's new insignia, pixel for pixel the `pips.shp`
      chevron or star it now wears, flashes in and rises to sit just
      above the health bar while a tapered four-point glint grows and
      fades on its upper corner, answered by a smaller one below (a
      third for elite), then fades. It is all overhead, on the top layer
      like the bar, and never reaches the bar itself. Only the owner and allies
      see it (it would mark a disguised unit), and it hides on cloaked
      units.
    - Firing anims (muzzle flashes and the like) follow their unit's FLH
      and facing instead of hanging where the shot left. The 13 weapons
      whose anim chains on with `Next=` keep the vanilla behaviour, since
      tracking resets the anim type and the chain would never end.
    - Lasers (all 145 `IsLaser`/`DiskLaser` weapons) keep their beam on
      the firer's barrel and on the target while it lasts.
    - Firing anims of air units (50 anims fired by aircraft and fly or
      jumpjet units) draw in their firer's layer: the engine put every
      attached anim on the ground layer, under the aircraft that fired it
      (`Layer.UseObjectLayer`, in `artmo.patch.ini`).
    - Turret recoil: the 34 turreted voxel vehicles that fire a gun shell
      kick turret and barrel back on each shot; their other weapons
      (missiles, bullets, beams, sprays) leave the turret still. MO marks
      no weapon as a gun, so the shell projectiles are listed in
      `rulesmo.patch.ini`.
    - Per-unit and per-weapon settings sit at the end of
      `rulesmo.patch.ini`, one section per object, with the rule behind
      each key in the block header; a contract test keeps every patch
      from updating one section in two places.
    - Decoys: the hover number would tell a decoy (`FakeOf`: fake
      Dominator, Foehn decoy squads, Libra clones and the like, 11
      pairs) from the real thing by its lower health, so decoys and every
      type that looks like the one they imitate show it to their own
      team only (`Phobos*HealthTeam`).
  - **MO under the Phobos engine**: Phobos fixes vanilla behaviour that
    MO's numbers were tuned on, and the fixes it brings are always on.
    Where that changed a unit's role or numbers, the layer puts MO's
    back:
    - Guardian GI: vanilla always fired Secondary at aircraft; Phobos
      can fire Primary too and, both using one warhead, picked the slower
      launcher (-30% anti-air, -1 range). `ForceAAWeapon` restores it.
      (Wolfhound, Norio and Kingsnake now fire their anti-air missiles
      at aircraft, which vanilla's rule prevented and their warheads
      were written for.)
    - Whipray: gattling units now fall back to their anti-air slot when
      the ground slot is a dummy, so the anti-air ship shelled the shore;
      `LandTargeting=1` keeps it on aircraft.
    - Strafing runs (Venom, Toxic Strike, Dustdevil, smoke and B-52
      bombers): Phobos repeats `Burst` on every shot of a run, 10
      projectiles instead of MO's 6; the runs fire 6 single shots on
      alternating barrels.
    - Salvo delays MO wrote but the engine never read (vehicles read
      only `BurstDelay0-3`, buildings none) now apply through
      `Burst.Delays`, with ROF raised so damage per second stays MO's:
      Buratino, Irritator, Sweeper, War Rig, Wormqueen.
    - The Allied AI's Chronosphere assault (24 teams) checked one
      superweapon and fired another it never owns, so it never jumped;
      `AIChronoSphereSW`/`AIChronoWarpSW` name MO's pair.
    - Artillery fired up or down a slope aims with the height included
      (`Arcing.AllowElevationInaccuracy=false`).
  - **`expandmo50.mix/`**: a new `EXPANDMO%02d.MIX` archive for Phobos-only
    files. It must be an expansion archive: the engine parses CSF tables and
    rules right after the `EXPANDMO` archives load and finds `ECACHE*`/
    `ELOCAL*` archives only later, which once left every `PHOBOS:*` label
    missing and crashed missions on start (exit `C0000409`). Its number sits
    below MO's 94-99, so it can only add files. Everything in it is built by
    `just assets` from `assets/phobos/expandmo50.mix/`, where it is edited.
    Names follow one scheme: `ph` + a four-letter family + a variant, with
    the family's shared file carrying the bare stem (`phring.pal`,
    `phfont.shp`, `phrank.pal`); the types that use them are named for
    what they draw (`PhobosRing24` draws `phring24.shp`, anim `PHRANKV`
    is `phrankv.shp`, display `PhobosUnitHealth`).
    - `phring11.shp` ... `phring58.shp` + `phring.pal`: the selection
      rings, the number being the ring's horizontal radius in pixels: 11
      for infantry, 24 for standard hulls, 30/38/46/58 for the larger hull
      classes; three health frames each (sheets of the same names).
    - `phfont.shp` + `phfonthp.pal` / `phfontfp.pal`: the 3x5 readout font
      in Phobos's 36-frame layout (sheet `phfont.png`), coloured for health
      or for factory progress (Phobos's `InfoType=FactoryProcess`, light
      blue).
    - `phrankv.shp`, `phranke.shp` + `phrank.pal`: the veteran and elite
      promotion anims, 20 frames on a 48x112 canvas centred on the unit
      (sheets `phrankv.png`, `phranke.png`), in the insignia's own
      colours; the art and its translucency keyframes are in
      `expandmo99.mix/artmo.patch.ini`.
    - `stringtable50.csf`: Chinese labels and hotkey names
      (`stringtable50.csf.toml`).
  - **`expandmo99.mix/`** (replacements of MO's own files and config patches):
    - `place.shp` (placement grid) and `pipbrd.shp` (health bar track),
      built from `assets/phobos/expandmo99.mix/` (`place.png`,
      `pipbrd.png`, which embed `palette.pal`, the palette the engine
      draws both with). Each grid state is a diamond with bright corners
      in one four-tone family: MO's pip green for buildable, the pip red
      for blocked, the readout blue for MO's white state. The bar track is
      near-black slate, the readout digits' shadow tone.
    - `uimd.patch.ini`: loading screen, credits roll speed, the counters, the
      super weapon sidebar layout, production bars, tooltips.
    - `artmo.patch.ini`: the promotion anims' art (rate, palette, layer,
      visibility, fade).
    - `rulesmo.patch.ini`: the HUD above plus modern RTS controls and fixes:
      building queues, factory tab switching, building type-select,
      attack-move, `ApproachTarget.StopWhenInRange`, extended aircraft
      missions, turret tracking, burst recount, jumpjet climb/tilt, fast
      boarding, `SortCameoByName`, `DistributeTargetingFrame`, `ShakeIsLocal`,
      blitter/lighting/targeting fixes, one share of height lighting for aircraft
      and jumpjets alike, floating income, shadows and wakes,
      combat alerts (unit voices only; MO has no `EVA_UnitsInCombat`), low box
      selection priority for all 10 harvesters, promotion anims, firing anims
      and lasers that follow their unit, turret recoil, and the opt-in
      vanilla fixes
      `DisableOveroptimizationInTargeting`, `AllowWeaponSelectAgainstWalls`,
      `[AI] EnablePowerSurplus`, detail-aware light and combat flashes
      (coloured ones included), and bombs stuck to a building (Ivan, C4,
      Arsonist and the like) shown and detonated at its centre instead of
      its top-left cell.
    - Several of these keys change gameplay, so online games need every player
      on the same profile.
  - **`expandmo96.mix/`**: `tab0{0..3}pp.shp`, the production bars, one set
    per side inside its nested sidebar archive, built from
    `assets/phobos/expandmo96.mix/`. Each side has one filmstrip,
    `tabpp.png`, whose palette is that side's `sidebar.pal` (Phobos
    draws the bars with it), so the sheet shows true colours in any
    editor. The engine loads both `SIDEC%02d.MIX` and `SIDEC%02dMD.MIX`,
    so one copy per side suffices: `sidec01md`, `sidec02md`, `sidec03md`
    and, because Foehn's `sidec04md.mix` holds no tab art, `sidec04`.
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

## Known Issues

- Hosting a LAN game can crash the client under Wine ("连线被拒" /
  connection refused in `LANGameLobby.SetUp`). MO's client starts its LAN
  listener on a new thread and connects its own lobby to
  `127.0.0.1:1233` straight away; Windows retries a refused localhost
  connect for about a second, which hides the race, while Wine fails at
  once. It happens intermittently (more often while the client is busy,
  such as right after a game exits or during a CnCNet reconnect) and is
  independent of the layers; retrying the room usually works. Joining
  someone else's LAN room is unaffected.

## Text-Level Patching

Instead of copying an entire config or map file just to change a few entries,
drop a patch file at the same relative path. A large patch may instead be a
directory of the same name holding fragments with the patch's own extension
(`expandmo99.mix/rulesmo.patch.ini/allied.ini`, `.../soviet.ini`); the
fragments apply in name order as one patch, the directory never appears in
the game folder, and any other file in it is an error:

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
