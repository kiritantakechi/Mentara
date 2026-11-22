# Mentara Overlay Layers

Each subdirectory here represents an independent overlay layer stacked on top of
the original Mental Omega game directory. The shipped profiles stack them in
this order (bottom to top):

```text
Mental Omega 3.3.6 game directory   (read-only)
└─ overlays/base     fixes and adjustments to MO itself; Ares 3.0p1, no Phobos
   └─ overlays/phobos   Phobos engine fixes and modernization on the fixed game
      └─ overlays/enhance   MO's units, buildings and AI rewritten with Phobos
```

`overlays/base` must keep working on its own (`just launch base`), so it holds
no Phobos keys, DLLs, or assets. Anything that needs `Phobos.dll` belongs in
`overlays/phobos`, which may assume the base fixes are present beneath it.
`overlays/phobos` changes how the game looks and fixes the engine but leaves
every unit's logic alone; `overlays/enhance` is where gameplay changes. A
profile may stop at any layer but never skips one (a contract test checks
`mentara.toml`), and each engine file ships in exactly one layer.

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
  - Side-wide triggers with a unit one country cannot build (fix 9):
    each country is forbidden one of its side's units and builds its own
    in that slot (`ForbiddenHouses` on one, `RequiredHouses` on the other,
    same prerequisites and category; where a country has two, the one
    firing the same weapons). 51 triggers raised the same team for all
    three countries of a side, so in the forbidden country it never
    filled and held a team slot until it dissolved: China's Borillos,
    Russia's Tesla Troopers and Halftracks, Latin's Demolition Trucks,
    PsiCorps' Adepts, Haihead's Raccoons, Last Bastion's Buzzards. MO had
    already written its own country twin for many of them (`FOETR135LB-G`,
    "Last Bastion - Condor Hunt", beside "Foehn - Buzzard Hunt"), but the
    side-wide original still fired for that country too. Each such trigger
    is switched off as in fix 8, and every country gets its own copy in
    the form of MO's twins: its two-letter code before `-G`, its label in
    the name in place of the side's, and in the forbidden country its own
    unit in the team (`SOVTR181RU-G`, "Russia - Tigr APCs Defense 1",
    raising "Russia Tigr APC Defense 1"). A country MO gave a twin keeps
    only that twin. That makes 110 copies and 8 new teams; a skirmish
    Russian AI raises "Russia Tigr APC Defense 1". Units no country builds
    (Ravager, Ruiner, Aeroblaze in its long mode) are only delivered or
    deployed, so the teams that ask for them are left as they are.
  - **`expandmo99.mix/rulesmo.patch.ini`**: the elite projectile of the
    Catastrophe, Centurion and Mammoth missiles kept vanilla's
    anti-air-only flag while every rookie form also hits the ground, so
    promotion took the ground attack away; it hits both. The skirmish
    AI's Cryocopter lacked the player version's `Chronoshift.Crushable=no`,
    so units chronoshifted onto it crushed it; it now resists like the
    player's. Values MO meant to match that drifted apart (found by
    comparing each family of related objects field by field):
    - Refunds and bounties: MO prices them at Cost/2 and Cost/5 and gives
      every construction yard 750 and 600. The Foehn yard had the two
      swapped, the Soviet yard refunded a refinery's 300, the Gharial kept
      an $800 unit's values at $2050, the Draco and Diverbee refunded less
      than half, and the Roadrunner's no-attack mode cost 50 more.
    - Rookie and elite weapons: the Gun Turret's two warheads were swapped
      (promotion weakened it against vehicles), the elite Paladin missile
      lost the rookie's scatter, the elite garrisoned Knightframe and the
      elite Basilisk shell hit below their rookies, the Harpy's rookie
      garrison bolt did 54 where its elite did 55, the elite Magnetron
      lost the rookie's beam style, and the rookie Desolator and Eradicator
      deploy beams set a colour only a rad eruption draws, which only their
      elites had.
    - Forms of one unit: the Lobber Speeder lost the Speeder's EMP
      resistance, the Athena Cannon showed on radar in hold-fire mode, the
      Bulldog had 5 more HP as a Painter, two AI copies dropped their
      originals' special threat, and the AI Zephyr had 10 HP less.
    - The Tech Military Docks never promoted the Angelshark, the campaign
      AI's Allied shipyard repaired nothing, the campaign Ion Storm spelt
      `Lightning.Separation` "Seperation", and the Mental Omega Device
      named a select voice soundmo never defines.
  - **`MentaraFixes.dll`** (Syringe hook DLL written in Zig, built from
    `assets/base/MentaraFixes.dll/` by `just assets`; Syringe injects it
    next to Ares. Its safety checks stay on and trap, so a hook that finds
    the game in a state it cannot handle stops there and the crash log
    names it): campaigns crashed under
    Wine with stock MO (exit `C0000005` at `0x00529A14`). The CnCNet spawner
    routes every `-SPAWN` game through the scenario reader that loads the
    multiplayer `[Header]` without resetting it first; campaign maps have no
    `[Header]`, so the start-point loop ran for whatever the uninitialized
    count held (leftover UTF-16 text under Wine, about 7.3 million) and ran
    off the scenario object. The hook skips that block in campaigns at
    `0x689EB0`, exactly like Phobos's `ScenarioClass_ReadMap_SkipHeaderInCampaign`,
    so the Ares-only and Phobos stacks behave alike and loading both is
    harmless (Ares 3.0p1 alone does not fix it). Syringe walks hook tables
    with a 16-byte stride, so its `syringe.zig` pads each entry to 16.
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
    It also makes Deploy on a selection its own inverse. The command
    first checks whether the selected deployers (infantry that deploy,
    `IsSimpleDeployer` units) are part deployed and part not, and if so
    sends Deploy only to those that are not; otherwise everyone toggles.
    Two kinds of unit sat in that check without taking part: a mode
    toggle (Ares `Convert.Deploy`, such as the Bulldog) comes out of its
    deploy as a fresh, undeployed type, and a unit Phobos leaves out of
    the command (`LowDeployPriority`, while a unit without it is
    selected) is never deployed. Either one always counted as "not
    deployed", so after Deploy dug a group's GIs in, the next Deploy
    left them dug in (and only flipped the Bulldogs back, or under Phobos
    did nothing at all). The hook at `0x00730B9C` leaves both out of
    that first check, reading `Convert.Deploy` and `LowDeployPriority`
    from the rules INI, so it judges only the units that keep a deployed
    state and receive the command. Upstream Phobos (master, November
    2026) still filters only in the command's second pass.
  - **`expandmo99.mix/artmo.patch.ini`**: seven civilian buildings (`CAWHSE`,
    `CAJHUT`, `CANHSE01/02`, `CAPRSNF`, `CASLUMA`, `CABRKK`) name a `cargo`
    palette that no MO archive ships (all 41 other custom palettes ship every
    theater variant). The engine already falls back to the theater palette,
    so the dangling `Palette=cargo` is dropped without changing their look.
    Keys YR reads under another name: the Foehn barracks' add-on sort
    (`PowerUp1YSort`, not `PowerUp1AnimYSort`), the Warpnode's, Warpshop's
    and Underground Lab's anim sorts (`ActiveAnim[Two|Three]YSort`), and the
    unnumbered `AddOccupy`/`RemoveOccupy` lines (YR reads numbered ones
    only) on two launch pads and two map props. Future Tank laser hits name
    `Explosion1`, which soundmo spells `Explosion01`. (A misspelt damaged
    upgrade key, `PowerUp1AnimDamaged`, needs no fix: an upgrade placed on
    a damaged host shows anyway, checked with a Psychplug on a 16% Pandora
    Hub.)
  - **`expandmo99.mix/soundmo.patch.ini`**: every game logged 281 samples
    no audio bag holds. Ten were typos of a sample that ships unused
    (Deviator, Dustdevil, Fury Drone, Grumble, Plague Splatter,
    Dybbuk-Evolver, Ramwagon, Saboteur voices); seven voice lists named a
    take MO never recorded, so a share of their picks was silent (half the
    Whipray's select clicks); 48 entries nothing plays held only missing
    samples (voice sets of cut units) and are emptied but kept, since maps
    play sounds by index. The Future Tank turret names an entry soundmo
    never defined, now made from its unused `vftrot*` samples; maps' short
    names for the beacon, Chrono Miner and warning sounds get aliases; two
    Draco turret entries and the MAD Mine slam spelt `FShift` and `Priority`
    wrong. The log now shows 59, the entries MO shipped no audio for.
  - **`expandmo99.mix/evamo.patch.ini`**: 22 campaign and co-op
    mission-fail triggers play `EVA_CriticalStrucureLost`, and three maps
    other misspelt or cut-off EVA names, so EVA stayed silent; each gets an
    alias of the line it means. Epsilon had no "Paratroopers ready"
    recording (YR's Yuri side had none); its "Reinforcements ready" stands
    in.
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
      in MO 3.3.6. The 174 assignments are listed in
      `rulesmo.patch.ini/technos.ini` with the rule that produced them.
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
      `rulesmo.patch.ini/technos.ini`.
    - Per-unit and per-weapon settings sit in `rulesmo.patch.ini/technos.ini`
      and `weapons.ini`, one section per object, with the rule behind each
      key at the top of the file; a contract test keeps every patch from
      updating one section in two places.
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
    - Cloaked open-topped transports: Ares 3.0 made a cloaked hull
      uncloak when its passengers fire. Phobos replaced that hook with
      `OpenTopped.DecloakToFire`, which its source defaults off (its docs
      say on), so passengers fired from an invisible Battle Tortoise,
      Centurion, Catastrophe or Jackal in a Haze Core or Hazequad field or
      under Shadow Ring. The layer turns it on. The Nautilus and the
      Magnetic emitter opt out: their built-in magnet gunners fire without
      uncloaking, so the hull stays hidden while its field pulses.
    - Spawned missiles (V3, V2, Dreadnought, Akula, Respite, Topol) fly
      to their target again (`MissileSpawnAttackCell=false`). Phobos sent
      them to the cell under it, which moved the blast off infantry's
      sub-cells and onto ground a moving unit had left.
    - The Nuclear Reactor's death: Phobos detonates a death weapon at
      once, which skips Ares's `PreImpactAnim`, so the reactor lost its
      nuke ball, its "nuke intro" sound and big craters before the blast.
      Its warhead's anim list now starts with a copy of MO's `NUKEBALL`
      that chains into the blast; the damage still lands at once.
    - With extended aircraft missions on, an airfield-bound aircraft that
      has no dock left crashes at once; vanilla crashed it too, but only
      when it next went idle.
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
    - `rulesmo.patch.ini/` (patch directory): `global.ini` holds the HUD
      above plus modern RTS controls and fixes, `technos.ini` and
      `weapons.ini` the per-unit and per-weapon settings. The global
      settings cover building queues, factory tab switching, building
      type-select, attack-move, `ApproachTarget.StopWhenInRange`, extended aircraft
      missions, turret tracking, burst recount, jumpjet climb/tilt, fast
      boarding, `SortCameoByName`, `DistributeTargetingFrame`, `ShakeIsLocal`,
      blitter/lighting/targeting fixes, one share of height lighting for aircraft
      and jumpjets alike, floating income, shadows and wakes,
      combat alerts (unit voices only; MO has no `EVA_UnitsInCombat`), low box
      selection priority for all 10 harvesters, area guard for the 2 armed
      ones (War Miner, Ultra Miner; players' only, so the AI's keep
      mining), low deploy priority for the
      84 vehicles whose Deploy does something (unpack, mode toggle, land,
      unload or a deploy ability, such as the Demolition Truck's blast), so
      Deploy on a mixed selection only digs in its infantry, attack-move
      follow for the 3 pure healers and, once full, the 3 mind controllers
      with a capacity, attack-move that keeps its cursor when engineers or
      spies are selected with an army, disguised infantry that allies see
      blink as their owner does, promotion anims, firing anims
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
- `overlays/enhance/`: Mental Omega's units, buildings, superweapons and
  skirmish AI rewritten with Phobos (profile `enhance`). Every object
  keeps its MO role, faction, tech level and cost; a rule changes how it
  plays that role, replacing a workaround MO had to build under Ares 3.0
  with the mechanic Phobos provides, or removing a limit that worked
  against the role. Rules apply to every object that fits them on all
  four sides, and the AI is given what it needs to use them.
  - **`expandmo99.mix/rulesmo.patch.ini/`** is a patch directory:
    `shared.ini` holds the charter, the rule catalogue, the global keys,
    the Phobos types and the objects several sides use; `allied.ini`,
    `soviet.ini`, `epsilon.ini` and `foehn.ini` hold one section per
    object, each key group under the name of the rule it follows. A
    contract test keeps each object in one section across the fragments,
    every Phobos type registered in its list (Phobos loads only listed
    types; others keep every default) and every added weapon, warhead and
    projectile in its YR list (`ExtraWarheads` ignores unlisted ones).
  - **`expandmo99.mix/artmo.patch.ini`**: art for the rules (the timer
    anims below).
  - **`expandmo99.mix/aimo.patch.ini/`** is a patch directory:
    `rewrites.ini` rewrites a few of MO's own skirmish scripts (below);
    `mentalai.ini` is the Mental AI's TaskForces, ScriptTypes and
    TeamTypes, generated.
  - **`INI/Game Options/Mental AI.patch.ini/`**: the Mental AI's
    triggers, generated into the client's "Mental AI Boost" option.
  - **`expandmo99.mix/rulesmo.patch.ini/mentalai.ini`**: the Mental
    AI's Phobos target lists, generated.
  - **Mental AI** ("终结级AI强化", MO's "Mental AI Boost" game option).
    MO's option only made the AI faster and richer: shorter team delays,
    factory cloning, start cash, a larger harvest bonus and more
    factories, with MO's ordinary teams. Here the option also replaces
    the AI's teams; MO's cheats stay. Unticked, the AI is MO's own with
    the layers' fixes.
    - The gate: the client merges the option file into the map, and
      `[Basic] IgnoreGlobalAITriggers=yes` switches off every aimo.ini
      trigger. The option file's own triggers are map triggers, so they
      still run; each must be listed in `[AITriggerTypesEnable]`, or a
      map trigger never forms. The TaskForces, ScriptTypes and TeamTypes
      sit in aimo.ini under fresh IDs, where nothing refers to them in a
      normal game. Redefining an MO TeamType from the map is avoided: a
      probe that changed only its `Script=` lost the whole team.
    - `mentara mentalai -p enhance` (`just mentalai`) generates the
      three fragments from the profile's rendered rules; `--check`
      reports stale output. The generator (`src/mentara/mentalai/`) names no
      unit: roles come from each unit's weapons against each armour
      class (damage per second against infantry, vehicles, buildings and
      aircraft), its hull and its flags (main battle tank, anti-infantry
      screen, anti-air, artillery, siege, healer or repairer, detector,
      hero, engineer, infiltrator, occupier, hijacker, stealth), and its
      damage against every armour in the rules. A country fields a unit if
      `Owner`/`RequiredHouses`/`ForbiddenHouses` and its prerequisites
      allow it from the buildings the country can own; a prerequisite
      no house can build (MO's `AILOCK`) is skipped, because the AI does
      not check unit prerequisites when it fills a team. A unit's tier
      is the tech level of the building that unlocks it (up to 4, 5-7,
      8 and up).
    - Volume: about 385 triggers per country, 4,616 in all on 3,134
      teams (MO's own AI has 1,200 triggers). Each team is a set of role
      slots, each filled by the best-scoring unit the country fields at
      the team's tier (at most six member types). The AI skips unit
      prerequisites, so each trigger holds its tier back: tier 1 runs
      until the country owns its tier-2 building (the one that unlocks
      most of that tier), higher tiers once it owns theirs.
    - Assault: a combined-arms **line** at every tier (four front
      tanks, an anti-infantry screen, anti-air, from tier 2 artillery, a
      healer or repairer and a detector, at tier 3 a hero) in three
      forms: **direct** (stage outside the base, break the defences,
      raze it), **flank** (Phobos 10056 drives round to the chosen
      enemy's farthest building and hits the base from behind) and
      **hunt** (each member hunts the army). From tier 2 a second trigger
      launches the line with the tier's **air strike** as Team2, in the
      same frame, and so a **siege** group (artillery that out-damages
      buildings, with tanks, screen and anti-air). **Factory blitzes**
      and **power raids** (fast vehicles that hurt buildings),
      **economy raids** on harvesters and refineries, **stealth raids**
      by cloaked units, and **feints**: fast units hit the chosen
      enemy's farthest buildings (Phobos 10005) to pull the defence away
      from the lines. From tier 2 a **grand line** doubles every seat of
      the tier's line (some 24 members, one team at a time): teams leave
      as they fill and a base's defences take them one by one, where a
      team twice the size meets them all at once.
    - Counters: every enemy unit worth answering (costing 1,000 or
      more, flying, shelling from the sea, or a hero) has a trigger per
      country that waits until the house's chosen enemy owns two (one
      of a hero or anything costing 2,000). It raises a squad of the
      units that do the most damage for their cost against that unit's
      own armour (custom armours included), shared by every enemy unit
      of the armour, which hunts them through a Phobos `[AITargetTypes]`
      list (`rulesmo.patch.ini/mentalai.ini`, where indices stay fixed)
      and raises its trigger's weight on its first kill (Phobos 14000).
      The squad is five of the hunters and nothing else: the
      highest-rated member picks a Phobos line's targets, and an escort
      that outranked the hunters picked with the wrong weapon (an
      anti-air leader found no ground target at all). Air
      is answered by anti-air holding the base, and so is an enemy
      airfield (**sky guard**). Such a guard stands ten minutes and
      stands down, and its trigger raises it again while the enemy
      still owns the thing: one that looped for good kept its place
      under the team cap, and its members out of every other team, long
      after the enemy's aircraft were gone (up to 20 such teams per
      house). When the enemy owns a strategic
      superweapon (a top-tech-level building, as MO's own snipe teams
      chose), a **superweapon snipe** goes for it by land, and an **air
      snipe** at once: a squadron of the side's heaviest bombers
      (Barracudas, Kirovs, Quetzals, as MO sent, or their like), which is
      the one squad that takes its members out of other teams (see
      "One priority"). So does a **hero
      drop**: the side's best building-wrecking hero rides its transport
      to that building, by land and by air (Tanya in an IFV or a
      Stallion, Volkov in a Borillo, Libra in a Stinger), gets out and
      wrecks it. MO's own Mental AI flew Tanya at silos this way, and
      the script is MO's: vanilla 47 and 46, which name the building by
      its index among the building types (MO's own numbers decode to the
      buildings its team names say). A Phobos line could not do it:
      Phobos keeps a team's leader while it lives, a transport that has
      unloaded and left the team included, and would pick the hero's
      targets with the transport's weapon (an unarmed Stallion has
      none).
    - Infiltration and holding ground: **spies** against power, radar,
      war factories, barracks, refineries, superweapons and tech labs,
      each try under a two-minute clock (a spy that could not reach its
      building held its team for good);
      **engineer drops** that load into a transport (Phobos 10103),
      drive next to power, a factory or the yard, unload and capture
      it; **hijackers** (Ares 67); **garrisons** of civilian buildings;
      the side's **battle bunkers**, **tank bunkers** and **bio
      reactors**; a **tech guard** for what the engineers took;
      **patrols** between refineries and power plants; the **base
      watch**; and **posts**, a watch's crew standing by the house's
      nearest defence, factory or power plant (Phobos 10053), as MO's
      own AI kept 167 of its teams beside its turrets and buildings.
      Posts are base-defence teams, so they share the engine's cap of
      three with the watches and add no standing team. Units that
      unfold into a turret or a minefield also **emplace** at home,
      beside the house's defences, as MO dug in its Irritators and
      Sweepers. The tech guard has a trigger per tech building that
      waits until the house owns one, and is built from tier-1 units.
    - Engineers: each tech building (`Capturable` and `NeedsEngineer`,
      built by no country: derricks, hospitals, airports, tech
      artillery, 28 kinds in MO) has a trigger that waits until a
      neutral house owns one (condition 7). The more kinds of tech lie
      untaken, the sooner the engineers go, two teams at once; with
      none left they are no longer raised (a single always-on trigger
      kept two engineers standing idle on maps without tech). MO's own
      AI did this for oil derricks and tech artillery only. A lone
      engineer mends a fallen bridge (Phobos target 37, a hut whose
      bridge is destroyed): it looks three times, half a minute apart,
      and is free again, where it used to wait by the huts for good.
    - Navy, once a shipyard stands (the engine keeps it off maps
      without water): **fleets** led by ships that can hurt the shore,
      **bombardment** groups of ships that shell buildings (a
      long-range torpedo boat is no artillery here), and **ship
      hunters** for the rest, submarines above all. Naval scripts use
      vanilla quarries, as MO's own fleets do: the engine gives each
      ship a target it can hit, where a Phobos line asks the leader,
      and a submarine leading found nothing on shore for the ships
      behind it. Hunters are raised only while the chosen enemy owns a
      shipyard: with nothing to hunt they ended their first objective
      at once, marked success and gained weight for it, and Russia
      raised 35 sub hunts against a USA with almost no navy (7 after).
    - Superweapon assaults: three **Chronosphere assaults** (next to the
      enemy's factories, power or defences), an **Iron Curtain charge**
      for a side with a team-cast curtain (vehicles under the curtain
      drive through the defences together), and a **boost assault** for
      each team-cast buff, built only from the units its warhead
      reaches (Overcharge: Tesla units; Irradiate: Soviet armour;
      Regen and Wonder Drugs, Kinetic Barrier: infantry; Rage,
      Illusion, Chronoboost, Glacial Screen) and casting it before the
      push.
    - The whole roster: every combat unit a country can build has a
      squad, as a coverage test against MO's own AI showed it should
      (MO's AI fielded 10 to 14 units per country that the slots alone
      never chose). Lines, sieges and raids come in up to three
      variants, the best unit per slot and then the second and third
      best (weights 100%, 60%, 40%). Each craft flies the sorties that
      suit it (see "Air") and each
      warship has a flotilla (artillery bombards, anti-ship hunts). Each
      hero leads an escort, and one that wrecks buildings goes for the
      construction yards first: M.A.D.M.A.N.'s AI twin, which MO's
      Haihead AI drove at the yards and this AI had never fielded,
      because heroes only filled an infantry slot. Units that unfold
      into a turret, a minefield, an outpost or a forward war factory
      deploy outside the enemy base (Fury Drone, Sweeper, Hazequad, War
      Rig, Mobile War Factory). Bomb planters go for what their bombs
      stick to, read from the planting warhead's `Verses` (Ivan, Ghost
      and the Arsonist buildings, the Repulsor vehicles and harvesters,
      Virus infantry), on vanilla quarries as MO's own teams did:
      Phobos judges the leader's weapon and found an Arsonist or a
      Repulsor no target. Each armed
      carrier rides out with the infantry that suit it, Phobos 10103
      seating them (see "Mounted infantry"). Engineers are also
      air-dropped by aircraft transport (the Stallion). A last pass gives every combat unit still unused a
      strike group of its own. Units whose weapons disable, freeze,
      mark or buff (EMP, attached effects, parasites, berserk) count as
      combat units and fill a disabler slot in the lines; a player's
      unit with an AI twin (`Convert.HumanToComputer`) gives way to the
      twin everywhere; anti-air is judged against the armours aircraft
      actually wear (MO's `f_*` armours, which anti-air warheads name in
      `Versus`), not vehicle armour, and Ares `ExtraWarheads` count.
    - Mounted infantry: MO's own AI seated a dozen kinds of infantry in
      an IFV, mixed crews in a Battle Fortress and flamethrowers by
      the Borillo-load; this AI had one crew per carrier, its best
      anti-infantry rider. A carrier now takes, at each tier from its
      own, the rider that hurts each class of target most aboard
      (vehicles, infantry, buildings); where it seats two, the first
      two of them side by side; and the side's hero with the main crew
      in the other carriers: 83 squads where there were 20, on 14
      kinds of carrier (USA's IFV with
      Guardian G.I.s, G.I.s, Enforcers, SEALs, or Tanya and three
      Guardians; a Battle Fortress of Guardians and SEALs; a Borillo of
      Tesla troopers, Flamethrowers or Desolators, or Volkov's). What a
      rider does aboard is read from the rules: a gunner vehicle
      (`Gunner`) fires the weapon its rider's `IFVMode` picks, so each
      IFV is judged with that weapon (a Guardian G.I. gives it missiles
      that also reach aircraft, a G.I. a machine gun, an engineer a
      repair arm); from inside an open-topped carrier only weapons that
      reach three cells count, so no dog or planted charge is seated
      there. Riders stay aboard a gunner or open-topped carrier. In a
      closed one (Borillo, Halftrack, Armadillo, Scavenger) they rode
      to their deaths unused; they now get out at the nearer gathering
      point (vanilla 8,0, which keeps carriers and riders in the team)
      and fight beside it. A carrier's crews together weigh about what
      its one crew did.
    - Into the base by transport: a **rush** loads a transport with the
      infantry that wreck the most buildings for their cost and rides
      in beside the enemy's power, factories or yard, where they get
      out and fight on vanilla quarries (six Flamethrowers in a
      Borillo, as MO's "Borillo Rush"; SEALs by Stallion; Brutes by
      Driller), and **saboteurs** ride the same way (Ivans by Borillo,
      SEALs by IFV or Stallion). Engineer drops, sabotage, rushes and
      hero drops are one family: who rides, how many, what they do
      once out, and which way the transport goes. There are three ways,
      by land, by air and by sea: a ship that beaches (a naval
      transport with an amphibious `MovementZone`: Voyager, Zubr,
      Mandjet, Watercat) carries every one of them too, six stormers
      where a Borillo seats six and a Stallion's SEALs three.
    - Across the water: MO's own AI never crossed water with its tanks.
      Its Voyagers and Zubrs sailed as warships, and no team of its
      1,200 used a Mandjet or a Watercat. A **landing** loads one such
      ship with what of a line fits its hold, tanks first (three
      Bulldogs or Rhinos, two riflemen and an anti-air trooper in
      twelve seats; two Abrams and nothing else at tier 3), sails to
      the chosen enemy's farthest power plant or factory (Phobos 10056:
      from the house's shipyard that is the far side of its base, away
      from where the lines come in), sets the party down and sends the
      ship home for the next one. Ashore the party takes vanilla
      quarries, as a rush does. Six squads a country, at every tier.
      The engine decides when a team goes by sea (gamemd 0x41FEE0,
      0x6F1FA0): one with a naval transport and no warship is raised
      only while its other members cannot reach the chosen enemy's
      base overland and an amphibious unit can, and one with no ship
      or aircraft only while they can. So on a map of islands the
      landings and the drops by sea are all the ground forces a house
      sends (it had none there before: every line, raid and rush was
      barred, and only fleets and aircraft went), and on any other map
      they are never raised.
    - Air: MO's own AI gave a gunship a hunt by class, a harvester
      hunt, a post over the base, a patrol and an escort; this AI gave
      every craft one squadron. Now a craft flies each sortie its
      weapons and airframe suit: a **squadron** strikes the class it
      hurts most; a **miner hunt** goes for the harvesters and then
      the vehicles sent after them (craft that hurt vehicles most and
      need no pad: Warhawk, Neonwasp, Diverbee); **air support**, a
      pair of any craft that stays up, flies at whatever is attacking
      the house (Phobos target 8, the enemies aiming at anything of
      the house's and those near the leader, nearest first), which is
      the base while it is attacked and the front while a line is,
      six answers of a kill each and then home; **air cover** is a
      pair of anti-air craft posted over the defences as a base-defence
      team (Rocketeers, Thors, Wolfhounds, Invaders, Buzzards, the
      Alanqa). Airfield-bound jets keep to strikes: each sortie of
      theirs needs pads. An **intercept** flight of the side's best
      air-to-air craft answers each kind of enemy airfield and goes
      for its aircraft, on their pads too (Phobos target 14); a kill
      raises its trigger's weight and a flight that ends without one
      lowers it. The
      tier's **air strike** takes a craft whose weapon only carries an
      effect along with its jets (a Cryocopter, a Hummingbird), as MO
      flew them at what its jets then hit. Air support marks nothing,
      so its trigger keeps a steady weight: a quiet patrol is no
      failure.
    - Specialists: **psychic assaults** send a side's mind controllers
      out together, as MO did four Adepts or Masterminds at a time
      (four Adepts, three Elites or two Masterminds with a screen and
      anti-air): they take the vehicles first, on vanilla quarries
      since a controller's weapon does no damage for Phobos to judge,
      and what they take joins the team. A **psychic post** stands two
      of them by the defences, and sends what they take after the
      enemy. An **infantry company** (four riflemen, three tank
      hunters, anti-air and a medic where the side has one) needs only
      the barracks, so it sets out while the war factory works through
      the teams ahead of it, and hunts the army rather than walk into
      a base's defences. Each ground unit whose weapon only carries an
      effect (the Bulldog painter, Suppressor, Oxidizer, Syncronin,
      Megalodon, Raccoon) rides two together with four tanks and
      anti-air, where it had a strike group of four of itself. A
      **support column** (anti-air, medics or mechanics, a detector
      and a screen) goes to the farthest of the house's own front-line
      tanks (Phobos 10060 on a list of them: from home, one at the
      front), holds beside it, and keeps joining the nearest (10054)
      six times over. A **miner guard** keeps to the house's nearest
      harvester, where raids find it away from the watch (Phobos skips
      a cloaked unit even of its own house, so Epsilon's guard holds at
      home while its Ghost Miners are cloaked).
    - Charges: a unit that is spent on its target (its primary weapon
      is `Suicide`) or must deploy to fire the only weapon it has
      (`DeployFireWeapon=0`) fills no slot: its one shot is not a
      tank's firepower, and as a team leader it found no target,
      because Phobos reads the undeployed weapon slot (every blitz a
      Demolition Truck led logged "can't find a new target" in play).
      Demolition Trucks, Bomb Buggies, Bloaticks and Demo Boats run
      straight at the class they hurt most on vanilla quarries, as MO's
      own "Demo Truck vs Factories" did, in a swarm their cost allows
      (two trucks, eight Bloaticks). With the Iron Curtain charged, the
      vehicles among them go in under it (MO's "Iron Truck").
    - Conduct: every TeamType key the engine reads for AI teams follows
      the squad's job, from a doctrine per kind of squad, then from its
      members. Direct lines, sieges and boost assaults drive straight in
      fighting on the way (`Aggressive`, no `AvoidThreats`); flanks route
      round the defences (`AvoidThreats`) and target only the chosen
      enemy (`OnlyTargetHouseEnemy`); hunting lines close ranks when
      harassed on the move (`Annoyance`); raids slip past fights to
      their target (not `Aggressive`, `AvoidThreats`); spies, engineers,
      hijackers, occupiers and charges ignore damage and keep going
      (`Suicide`); engineer drops send their transport home after
      unloading (`TransportsReturnOnUnload`, with vanilla load 14, which
      saves its place); guards and the base watch close ranks and refill
      when worn to a third (`Reinforce`). A squad with slow and fast
      members gathers on the slow ones (`GuardSlower`), and one with
      mind controllers keeps the units it takes (`MindControlDecision`:
      join the team, or hunt for guards). `Loadable`, `Full`, `Whiner`,
      `LooseRecruit` and `Prebuild` stay off: AI teams are created empty
      and filled by production, so the engine never reads them.
    - One priority: a team takes recruitable members out of any team of
      lower `Priority`, whether that team is still forming or already
      on its way (gamemd 0x6F1ED9). The squads once ranked by kind (the
      MCV 10, superweapon assaults 8, counters 7, agents 6, lines 5,
      raids 4, guards and feints 3, garrisons 2), and a game with a
      probe at each script's first line showed what that did: lines
      stripped the raids of their vehicles as fast as the factories
      built them, so of 137 blitzes, power raids and economy raids
      created in nine minutes, 14 ever set out. Every team now has
      priority 5 and keeps its members until it ends; then they return
      to the pool for the next team. A higher priority would let a team
      that answers the enemy skip the wait for the factories, as MO's
      own answers did, but the engine chooses whom it strips badly: an
      empty team takes the unit of its type nearest the map's first
      cell (its north corner), wherever the house stands, and then the
      ones nearest that (gamemd 0x6EAA90; an AI team has no waypoint to
      measure from), and marching and fighting units are as free to
      take as idle ones (only a few missions, Hunt among them, bar
      recruiting). A probe game showed it: USA kept three G.I.s at home
      and three at the enemy's gate, each as a team, and a team of
      higher priority that wanted three filled in the frame it was
      created, ten times: four times by emptying the team at the gate,
      six with the idle G.I.s its predecessor had left there, and never
      from the team at home. It emptied a marching team the same way. A
      ground team raised that way
      would pull a line out of its attack, and a mixed one would hold
      what it took while it waited for the rest. So one squad alone is
      urgent (priority 6): the air snipe, aircraft of one type, which
      are retasked from wherever they fly, need nothing else to leave,
      and for airfield-bound craft could not form otherwise, their
      pads being taken by the squadron that flies them.
    - Unpredictability: Phobos 16003 skips the next line with a chance,
      and when that line is a vanilla jump over a block, the block runs
      with that chance; each team rolls for itself (the game's synced
      random, the same on every machine). A direct line gathers again
      nearer the base half the time (Ares 53 with a negative distance),
      fights at the gathering point or rushes, and strikes the factories
      or the power first (a power cut takes the defences off line) before
      the defences; a flank circles to the far power plants or the far
      buildings and hits power or factories first; sieges sometimes shell
      the power first; raids, feints, air strikes and navies take their
      targets in an order they roll.
    - Two teams at once: a trigger's Team2 starts in the same frame, so
      a **pincer** sends a direct line and a flank together, **feint and
      strike** a line and a feint that pulls the defence off it, and an
      **escorted siege** a siege behind a hunting line, beside the line
      and siege with air support. Each such call leads with a TeamType
      of its own, its squad's task force and script under the call's
      name: the engine settles weights for every trigger whose Team1 is
      the ended team's type, so a pincer that shared the line's
      TeamType rose and fell with every plain line. The log names them
      apart, too.
    - Opportunities: when the chosen enemy has under 100 power to spare
      (condition 2), a **grid strike** (a power raid) tips it into a
      blackout; when it drains more than it makes (condition 3) its
      defences are off line, and a **blackout assault** (a line with a
      blitz or a feint) goes in at high weight; under 2,000 credits
      (condition 4) every harvester it loses hurts at once, and a
      **starve** raid goes for them; down to 500, a **finishing hunt**
      goes after what it has left, with an economy raid.
    - Learning: the engine settles a trigger's weight when a team it
      leads ends: up if the team ran `49,0`, down if not, and by more
      the longer its record runs one way (gamemd 0x6E8DE0, 0x41FD60,
      0x41FE20; MO's deltas are 5). The scripts marked success after
      razing every building, which no team lives to, so every attack
      trigger sank to its floor while garrisons and bunkers, which
      marked it on entering, rose to their ceiling: nothing was learnt.
      `49,0` now stands where a team's first objective ends, under a
      Phobos 16001 clock or because nothing of the class is left: a
      line alive 100 seconds into the defences, a raid that has made
      one kill of its class (Phobos's single-kill attack lines) or is
      alive 150 seconds after it set out, a squadron still flying after
      a strike of up to 90 seconds on each of its two classes, a
      transport that unloaded its engineers, a charge that reached its
      staging line. A team wiped out before that costs its trigger
      weight. Against heavy anti-air the air triggers fall
      to half weight; a flank that keeps getting through doubles. The
      clocks also move a line on from the defences to the buildings
      instead of chasing the last turret. A script that cannot tell how
      it fared marks nothing, and its trigger's weight is fixed
      (minimum and maximum equal the weight): a spy or an engineer is
      spent when it succeeds, and a garrison is in its building either
      way.
    - Tech: the AI does not check unit prerequisites, so the building a
      trigger waits for is all that holds a unit back. Every trigger
      that waits for an own building fields nothing above that
      building's tier (a test holds this): engineer drops wait for the
      tier of their transport, and a boost assault takes nothing above
      the building that grants its buff. A trigger has one condition,
      so one that waits on the enemy (counters, snipes, sky guards,
      opportunities) cannot also wait for a building, and, as in MO's
      own AI (its spy and snipe triggers), may field a unit before its
      tech stands.
    - Mind controllers: tier-2 and tier-3 lines take the side's mind
      controllers (Yuri clones, Yuri Prime, the Mastermind), and keep
      what they take.
    - Turnover: the AI builds for its oldest unfilled team first and
      hands each new unit to the oldest team that wants it (the main
      loop walks the teams in creation order, gamemd 0x55B502; Phobos
      `UpdateVehicleProduction`). A team therefore waits while every
      older one fills, and the wait from a trigger firing to its team
      setting out grows with the number of teams forming. A probe at
      each script's first line measured it. With MO Mental's roll every
      100 frames and a cap of 150 teams (an earlier round here raised
      MO's 100), 879 teams were created in nine minutes and 518 set
      out; rolling half as often set out as many (502 of 743), so the
      factories, not the rolls, bound the army, and the extra teams
      only lengthened the queue. A house rolls far faster than its
      factories fill a team, so it always stands at the cap, and the cap
      is the queue: matching each team's first script line to its
      creation in the log, a team with vehicles set out some 60 teams
      after its roll at a cap of 80 (a third of a game: lines 56,
      flanks 61, the base watch 56, a superweapon snipe 49), 36 at a
      cap of 40 and 26 at 30, while infantry and air teams left at
      once. No fewer lines set out at the lower caps (114 direct,
      flanking and hunting lines at 80, 140 at 30; games differ by more
      than that between two runs), so the factories bound the army and
      the cap only the wait: at 80 a house was still fielding what it
      had rolled a third of a game ago, and answered the enemy's
      superweapon a queue late. The cap is now 40/30/20 (MO's
      100/75/50 holds teams half the size). An empty team is dissolved
      after
      `DissolveUnfilledTeamDelay` and loses its turn: a squad of one
      contended type (four main tanks for an economy raid) stayed empty
      past MO's 5,000 frames nearly every time and was raised again at
      the back of the queue (one of 22 set out). At 15,000 six of 21
      set out, and with the cap at 40 four of 16 and 11 of 19: the wait
      at that cap is itself about 15,000 frames, so half of them were
      dissolved a moment before their turn. The delay is 30,000 here:
      15 of 17 economy raids set out, and blitzes, power and economy
      raids together 56 of 76 (14 of 137 at the start). Members of
      an ended team rejoin the pool (Phobos `SetRecruitableOnLiberate`),
      where a squad recruits them before the factories build new ones.
      An agent team with nothing to enter tries three times, half a
      minute apart, and then ends: its spy or engineers serve the next
      team instead of holding a place under the cap.
    - How they fight: lines and sieges regroup, stage outside the enemy
      base (vanilla 53, under a Phobos 16001 timeout), fight there in
      Phobos Area Guard (10100), where every member picks its own
      target, then push with vanilla `0,q` on defences and structures,
      which hands the team's focus only to members without a target.
      Phobos attack lines are kept for single-role teams (raids,
      counters, agents): they give every member the leader's target
      each frame, so a mixed team's anti-air and medics would chase a
      building. `LeadershipRating` ranks the slots (front line 12,
      artillery 10, hero 9, screen 8, anti-air 6, support 4; a unit
      takes its highest), so a tank leads and picks targets instead of
      a dog or a hero (MO rates heroes 99). Attack teams are
      `Aggressive`.
    - Handling: three Phobos keys only AI-owned units obey, each staged
      with pre-placed units and screenshots before use. (1) G.I.s,
      Guardian G.I.s and Snipers deploy when their target is in reach
      of the deployed weapon (`InfantryAutoDeploy`, already set on the
      three in the rules for every AI): with it forced off in the map
      they fought standing, with it on they dug in. They are the three
      whose deployed weapon reaches at least as far as the other; a
      Desolator or a Yuri clone, whose deployed weapon is a blast at
      its feet, must not. (2) A gun that outranges every main battle
      tank keeps its distance while it reloads (`KeepRange`, switched
      on for AI houses in the option file): the kept distance is the
      range less a cell (two for infantry), for weapons that reload in
      60 frames or more, on units that neither dig in nor charge; 26
      weapons qualify (the Zephyr's howitzer, V3 and Ventrex
      launchers, the Prism tank, Stalkers, Morales, the Virus). Three
      AI howitzers against three tanks that closed on them died in
      place without it and killed none; with it they backed away while
      reloading and killed all three. (3) An idle AI unit looks for a target
      every 14 frames, and 18 on Area Guard, where MO has 27 and 36
      (`AINormalTargetingDelay` and its kin): the gain is a third of a
      second in noticing a new enemy, too small to see in a staged
      duel, so only the engine's code vouches for it. It costs no
      speed that shows: a four-AI game with the keys ran 907 ticks of
      a clock team in its fixed nine minutes, one without them 856
      (whose clock team was killed and raised again 14 times, so its
      count runs low).
    - Not used, broken in Phobos v0.5-alpha2: 12000 (never waits),
      10102 (never regroups), 18000, the "random" list attacks, and
      10104's charge test.
    - Played (four Mental AIs on Tea Moon Cake, `enhance`, the game's
      log names every team it creates): with the option ticked only
      Mental teams form; unticked, MO's own. A copy of the line script
      that logs each stage showed USA's tier-2 lines conscripting 76
      times, staging 75 times, clearing defences 37 times and
      structures 33 times in seven minutes (the rest died on the way);
      in one game Russia's base fell by minute seven. Fixed from play:
      air strikes on Phobos attack lines found no target for Comanches
      and looped every frame, so they use vanilla quarries as MO's air
      teams do; engineers and spies with nothing to enter ended and were
      raised again on every roll; airfield-bound strikes asked for more
      craft than the pads hold, so the AI abandoned their production.
      Not yet checked: whether `Aggressive` fights on the move, and
      anti-air under Area Guard.
    - Superweapons: the AI fires most superweapons on its own (Ares
      `SW.AITargeting`), but one with `SW.AITargeting=IronCurtain` waits
      for a team to request its `SW.Group` (Ares action 55) and fires on
      that team. MO's teams made those requests, so the gate would have
      silenced them; the generator reads them from the rules instead. A
      country's lines and sieges cast every such group it can own at the
      staging point, before the push (Iron Curtain, Irradiate,
      Overcharge, Drakuv, Nuclear Path; Chronoboost, Glacial Screen;
      Rage, the drugs, Illusion, Kinetic Barrier, Ruiner; Nanofiber,
      Decoys, Spinblade, Megaarena), each under a 10-second timeout
      because action 55 waits while one is almost charged. A group that
      delivers only harvesters (Warp Miners) is cast by the base watch.
      `SW.AllowAI=no` groups (Chronolift) are skipped. A country with a
      Chronosphere the AI may use gets a **Chronosphere assault**: front
      tanks, artillery and anti-air vehicles (the sphere moves a 3x3
      area and kills the infantry it moves) whose trigger waits for "the
      Chronosphere is charged"; vanilla action 57 jumps them next to the
      enemy's factories with the sphere the phobos layer pins, where MO's
      own assault used action 56 and skipped the jump. Airfield-bound
      strike craft share one airfield's pads across the tiers and are
      not cloned (Phobos `ForbidParallelAIQueues`, set in the option
      file): Mental AI's cloning builds a copy per extra factory, a copy
      of such a craft has no pad, and the AI abandoned its production
      (39 Foxtrots in one game, none after).
    - Superweapons played (same four AIs, nine minutes): Warp Miners
      fired 26 times, Spinblade 24, Decoy Team 24, Nanofiber 21,
      Chronoboost 21, Regen Drugs 7, Illusion 6, and USA's Chronosphere
      assault formed 15 times with 14 sphere jumps; with the same AIs
      and no casts none of these fired. Russia, at the first start
      position, fell first in every four-AI game; in a Russia-Latin game
      Drakuv fired 11 times, Irradiate 5, Overcharge 5 and the Iron
      Curtain 3. Nuclear Path was not seen.
    - The expanded set played (four Mental AIs, nine minutes): 1,234
      teams formed, from every family: 75 direct lines, 63 flanks, 59
      hunts, 65 feints, 49 blitzes, 47 power and 38 economy raids, 81
      garrisons, 34 bio-reactor and 18 battle-bunker teams, spies on
      every class of building (108), 35 engineer drops, counters against
      named enemy units (Mastodon, Libra, Tanya, Tesla tanks, Gharials,
      enemy jets), superweapon snipes, sky guards, boost assaults
      (Regen, Illusion, Overcharge, Rage, Chronoboost, Irradiate), six
      Iron Curtain charges and four of each Chronosphere assault; the
      casts fired (Overcharge 11, Drakuv 10, Rage 6, Iron Curtain 5).
      Airfield-bound strike craft are lost and raised again often
      (about 40 teams of two per tier in nine minutes) but no longer
      abandoned.
    - With the per-role conduct, random branches and two-team calls (same
      four AIs): the scripts ran with no unknown action, every family
      formed, and the casts fired (Overcharge 12, Drakuv 9, Irradiate 8,
      Iron Curtain 6, five Curtain Charges). PsiCorps lost its yard
      twice and fell by minute four, so its controllers were not seen
      fighting; the others' guards refilled instead of being raised
      again (15 base-watch teams against 49).
    - With the whole roster (Russia, USA, PsiCorps and Haihead, nine
      minutes): 969 teams from every family, the new ones included:
      squadrons of a dozen aircraft types, carriers (Borillo, IFV,
      Jackal, Sting, Scavenger), strike groups, bombers (Ivan, Virus,
      Repulsor, Ghost), forward deployers, air drops, and every hero:
      Haihead's M.A.D.M.A.N. twin formed twice and reached its staging
      cell outside the enemy base on its way to the yards, beside
      Tanya, Volkov, Chitzkoi, Libra, Siberian Fin and Sicali. No
      unknown script action, and production abandoned only a handful of
      times.
    - With learning, one priority and the shorter queue (Russia, USA,
      PsiCorps and Last Bastion on Tea Moon Cake, nine minutes at full
      speed, about an hour of game time; probes in a scratch layer log
      each script's first line, first attack and success mark): 779
      teams created, 529 set out, 228 reached their mark. Of those
      that set out, the mark was reached by 29 of 68 direct lines, 17
      of 39 flanks, 26 of 34 hunts, 5 of 7 sieges, 90 of 95 air
      strikes, 13 of 40 feints, 6 of 18 blitzes, 4 of 22 power raids
      and 9 of 10 Bloatick charges; so on this map against these
      enemies the hunts, sieges and air strikes gain weight and the
      break-in lines and feints lose it. The two-team calls formed
      under their own names (Line + Air 14, Feint and Strike 12,
      Pincer 7, Siege + Air 3), engineers went out for the map's tech
      (11 teams), and no script logged an unknown action.
    - The navy played (Russia against USA on Dueling Islands, nine
      minutes): 45 naval teams formed (29 flotillas, 7 sub hunts, 6
      bombardments, 3 fleets) and all 39 that set out engaged; land
      teams crossed the bridges, and engineers went out to mend them
      (11 bridge repair teams).
    - With the shorter queue, guards that stand down, hero drops, grand
      lines and four-carrier mounted lines (the same four AIs and map,
      three games, the last on the shipped values): 531 to 598 teams
      created, 393 to 438 set out, 139 to 168 reached their mark (fewer
      marks than before because fewer air strikes fly, and nearly every
      air strike reaches its mark). A team with vehicles waited 34 to
      38 teams. Grand lines set out 20 times and 11 lived through the
      break-in; mounted lines with four carriers 5 of 23, against 4 of
      29 with two. Six hero drops set out and one is known to have
      reached its building (Volkov in a Borillo, at a weather control
      device); the log does not say what became of the other five
      (Tanya in an IFV among them), and the trigger loses weight for
      each that does not come through. Sky guards were raised 5 to 12
      times a game, and no script logged an unknown action. Two games
      at one setting differ by a quarter in the lines they send, so only
      what holds in every game is claimed here.
    - With air snipes (the same four AIs, one game): seven were raised
      and five set out, a team or two after their roll, where the three
      snipes by land raised in the same game were still waiting for the
      factories at its end. USA's first formed in the frame it was
      raised, out of the Barracudas it already had, and reached its
      mark (alive when the silo fell or its clock ran out), as did its
      second; PsiCorps's three set out and none reached the mark;
      Russia's four Kirovs were not built in time. 539 teams created,
      435 set out, no unknown action.
    - With mounted crews, rushes, posts and the handling keys (the same
      four AIs, one game): 516 teams created, 403 set out, no unknown
      action. Fifteen kinds of mounted squad were raised and ten set
      out (IFVs with Guardian G.I.s and with SEALs, Borillos and
      Scavengers of Tesla troopers and Flamethrowers, Jackals,
      Gharials, Stingers with Libra); none lived through the break-in,
      so their triggers lose weight as they did before (5 of 23 in the
      games before). Four rushes and four sabotage teams set out; three
      rushes and one sabotage team reached their building and got out,
      and none was alive 150 seconds later. Twelve posts and two home
      emplacements formed beside four base watches.
    - With the air sorties, the specialists and the sea (one game
      each): on land (the same four AIs) 540 teams were created and
      442 set out. Infantry companies were the readiest of all: 40
      raised, 38 set out, 28 alive at their mark. Eight air support
      pairs, four intercept flights and eight support columns were
      raised and five, three and seven set out; none of their Phobos
      lines failed to find a target or a tank to join. Two psychic
      assaults, three specialist squads and a miner hunt were raised
      among 540, too few to judge. No sea team was raised there, nor
      on Dueling Islands, whose two bases a land route joins. On Casual
      Encounter, an Islands map (Russia against USA, with MO's Islands
      code merged as the client does), the engine raised no line,
      company or rush and did raise nine landings and nine engineer
      drops by sea: six of each set out, two engineer drops reached
      their building, and when Russia fell at frame 40,122 to the
      USA's fleet and aircraft two landings were under way and three
      Bulldogs stood on its island. No landing was seen to storm a
      base that still stood. The USA's interceptors flew 13 times
      there, nine of them finding no aircraft and marking success all
      the same; the mark has since been taken out of their script,
      which has not been played again.
  - Rules in the first wave:
    - **aura**: 19 field emitters (Ultra Dome, Lightning Rod, Repair
      Crane, Iron Guard, Disruptor, Chimera Core, Haze Core, Magnetic
      Beam, Nanocoat Regulator, Spinblade, SODAR, Orcinus, Megaarena and
      the tech Shield Generator and Expansion Post) fire on their own
      cell. MO made them "attack" a friendly with a 384-cell relay, fired
      them from a hidden auto superweapon (which the AI only polls every
      ~110 frames), or from a hidden passenger. A hidden superweapon fires
      every building it lists, so all buildings that share one move
      together: the Expansion Post grants the Repair Crane's, which would
      otherwise still pulse the Crane on top of its own weapon.
    - **anti-air**: 13 anti-air units and defences fire their real weapon
      as Primary instead of hiding it behind a dummy.
    - **torpedo**: torpedoes are stopped by land.
    - **pursuit**: 20 contact units (dogs, drones, Ivan, Brute, demo
      trucks and the like) chase the target instead of its range arc.
    - **siege-transport**: Centurion, Catastrophe, Battle Tortoise and
      Nautilus fight at their own range, not their passengers'.
    - **carrier**: carriers' craft share the carrier's rank, turn back
      2 cells past its launch range, and launch 10 frames apart.
    - **dead-zone**: Centurion and Catastrophe fire missiles inside their
      gun's minimum range.
    - **gattling**: Cavalier and Paladin keep their escalation between
      targets; the Cryocopter's freeze restarts per target.
    - **infiltrator**: disguised infiltrators move at their disguise's
      speed.
    - **stack-cap**: Syncronin bonds, Oxidizer marks and Ruiner
      suppression are capped Phobos effects instead of unlimited Ares
      stacks; Oxidizers and Ruiners move on to a fresh target.
    - **jammer**: a disabled transport also silences its passengers.
    - AI: capital ships may bombard land in range, patrols guard actively
      (Phobos action 10100), the capital-ship superweapon raid attacks,
      AI GIs, Guardian GIs and Snipers deploy to fire, and the AI's spare
      power scales with its drain (`aimo.patch.ini/rewrites.ini`,
      `shared.ini`).
  - Rules in the second wave:
    - **timer**: objects whose lifetime was an anim damaging them and that
      nothing else can hurt (Elite Reserves, Kingsnake portal, vision
      tower, Magnetic Beam, Signal Jammer) die by `AutoDeath` on the frame
      the anim would have killed them: HP / (Damage x Versus) x
      (900 // Rate), plus any effect delay (1400, 2730, 1500, 540, 1800
      frames). The engine advances an anim's damage only on its own frame
      steps, `900 // Rate` game frames apart (integer division). Objects
      enemies can damage too (Lightning Rod, Knightfall beacon, tunnels,
      Disruptor, War Rig) keep MO's decay as part of their durability.
    - **self-superweapon**: Gear Change, which sent an invisible
      hunter-seeker only to set off its warhead over its owner's base,
      fires that warhead at its Industrial Plant on one click
      (`GenericWarhead` with `SW.UseAITargeting`/`Self`); the AI, which
      MO barred from it, can now use it.
    - **upgrade-in-place**: Nanofiber Sync converts the infantry it
      upgrades (Phobos `ConvertN`) instead of killing them for a death
      anim to spawn the upgrade, so they keep rank, group, orders and
      effects and count no loss, and an extra warhead heals them to full
      as MO's newborns were.
    - **close-range**: the Cyclops' double damage within 3.5 cells is a
      second weapon it switches to there (`ForceWeapon.InRange`), with
      MO's glow via a feedback weapon, instead of a hidden passenger.
    - **ai-twin**: the Cryocopter's AI copy uses the player's beams; a
      target filter without empty cells does what the projectile flag
      that forced the copy did.
    - **rider**: 21 projectiles that set off a 1-damage effect warhead
      (Tesla EMP, driver kill, slows, marks, garrison clearing) through an
      airburst helper weapon carry it as `ExtraWarheads`, landing on the
      impact point instead of a cluster cell beside it.
  - Rules in the third wave:
    - **self-superweapon** also covers Nanocharge, whose invisible 1 HP
      seeker existed only to die and set off its warhead.
    - **stack-cap** also covers the Syncronaut: its bond rides the rider
      warhead onto its target and counts towards the same 3 bonds. MO let
      three Syncronauts stack x7.45 damage taken; the cap holds x1.95.
    - **carrier**: since rank now reaches the craft, carriers take 50% of
      their craft's kill value instead of 75%, so they rank up after 1.5x
      the kills (an elite Enterprise's Hornets hit twice as hard).
    - **iron-curtain**: player-controlled units neither pick nor return
      fire at targets under the Iron Curtain or Iron Guard, as the AI
      already did (`AutoTarget.IronCurtained=false`); force-fire still
      works.
    - **rider** takes helpers of any damage: the Riot Trooper's stun, the
      Rahn's Clairvoyant kill and the Cryocopter's freeze stages.
  - Rules in the fourth wave:
    - **demolition**: weapons built to raze buildings (at least 115%
      against wood and steel: Siege Cadre, Prism Tank, Dolphin, Volkov,
      Barracuda and the IFV and Scavenger modes that carry them) pick idle
      enemy buildings in range for players, as they always did for the AI.
    - **radiation**: a radiation field belongs to the unit that laid it
      (Desolator, Eradicator, Nuwa Cannon, Reaper), so its kills count for
      that unit's rank and its owner's score; victims may fire back.
    - **jammer** also covers EMP: an open-topped transport an EMP shut
      down silences its passengers too.
    - **rider** follows chains of helpers that go off on the spot (the
      Megalodon's wind then blade, the Backwarp's five repair pulses, the
      Cryocopter's last freeze stage) and takes a helper whose only extra
      is its weapon's own firing sound (the Suppressor's bomb).
    - **aura**: the Spinblade's Golden Wind fires its armour buff from an
      instant shell instead of one dropped from the sky.
    - **ai-superweapon**: seven superweapons MO kept from the AI (AI
      targeting `None`) get the targeting MO already gives the same kind
      of delivery: Instant Shelter and the Repair Drones land around the
      base when it is attacked, the Kingsnake
      nest at its platform when attacked (as Elite Reserves), the Sweeper
      drop at the favourite enemy's base (as Tank Drop), naval mines on
      enemy vessels near the AI's yards (as the MAD Mine), and the Decoy
      Squadron with the decoy team's script (as Decoy Team). Dropped
      Sweepers deploy and Repair Drones guard on landing
      (`AIParadropMission`); every other vehicle the AI drops hunts,
      Phobos 0.5's fix of vanilla leaving them on Guard while its
      paradropped infantry hunted. Quick Fort (a bunker that MO's AI
      mans only through rare one-unit bunker teams), Raven, Vision,
      Zephyr Beacon and Golden Wind stay player-only. Shelters and
      drones use `DropPod` targeting: a random direction, one to two
      base radii from the base centre (the engine holds the radius
      between 3 and 8 cells). MO's Disruptor lands on the centre cell
      itself (`Base`), which suits an aura that wears out; a shelter or
      a drone stays for good, and on that cell each took the free place
      nearest the last, so the pile grew around the war factory. Risks
      the AI accepts: Repair Drones gather around a base that is often
      attacked, and a Kingsnake nest hunts the attackers for its
      lifetime.
  - Rules in the fifth wave:
    - **base-centre**: 30 buildings placed out in the field, 21 that a
      superweapon drops (beacons, towers, shelters, minefields) and 9
      posts that support vehicles unpack into (Grumble, SODAR, Orcinus,
      Sweeper, Boidmachine and the like), no longer count towards their
      owner's base centre (`IgnoreForBaseCenter`). That point is where
      the AI's base-aimed superweapons land and where enemy paradrops
      aim, and each field building pulled it toward the front by its cost
      (4 Grumbles 60 cells out moved it about 12 cells). Yards,
      factories, refineries and anything a yard can build still count.
    - **confusion**: a berserked unit attacks what is in its weapon's
      reach instead of going on Hunt (`BerzerkMission=Guard`), which
      could send it across the map, firing at nothing, for the whole
      effect (Irritator, Deviant, Whipray, Shark, Confusion Grid, Chaos
      Touch).
    - **ai-superweapon**: the AI drops Hijackers on the favourite enemy's
      base (as Tank Drop); they hunt, stealing or bombing the vehicles
      they find. The AI also looks at its superweapons every 30 frames
      instead of every 106-112 (`AISuperWeaponDelay`), so its Tick Trap
      tunnels and Knightfall beacons spawn at a player's rate and its
      defensive drops answer an attack within 2 seconds.
    - **ai-twin**: the 8 AI-only copies (Thor, Zephyr, Vulture, Chrono
      Legionnaire, Clairvoyant, Cryocopter, Morales, MAD Tank) become the
      player's version when a player captures one, with its deploy
      abilities and weapons, and a player's unit the AI captures becomes
      the AI's copy (`Convert.ComputerToHuman`/`HumanToComputer`). Deploy
      modes MO also locks to the AI are not copies and keep their type.
    - **jammer** also covers a hull a Zorb's tractor beam holds aloft.
  - Checked in game (skirmish scenes; superweapons charged by a test-only
    probe layer stacked on `enhance`):
    - The aura buildings fire with no target (buffs, cloaking, repair 293
      to 480 HP).
    - The Patriot downs a Kirov with its Primary.
    - A Ruiner silences three infantry at once.
    - Gear Change fires on one click and shuts both factories down.
    - Nanofiber Sync turns a damaged Knightframe into a Kingsframe at its
      full 380 HP.
    - The Cyclops glows while firing its close weapon.
    - The Tesla EMP sparkles as under MO.
    - Player and AI Cryocopters both freeze a tank.
    - The Magnetic Beam vanishes on time, and the vision tower and Signal
      Jammer vanish at the same moment as under MO.
    - Each scene below was also played under `default`, where MO's
      behaviour shows:
      - A Centurion and a Catastrophe kill a tank inside their gun's
        minimum range with their missiles; under MO they stand idle.
      - Loaded with conscripts, both engage tanks at 12 and 7 cells on
        Guard; under MO they never engage.
      - An elite Quetzal's Seeker drones carry the elite star.
      - A Catastrophe jammed by a Raccoon goes silent with its passenger;
        under MO the conscript inside kills three GIs.
      - With a Repair Crane and an Expansion Post, the Crane superweapon
        never fires (9 times in the same scene under MO).
    - Riders land as under MO: Morales kills a tank's driver, and the
      Blizzard's slow, the Plague Splatter's corrosion, the Raccoon's
      weapon lock and the Scourge's EMP all apply.
    - The Syncronin's bond attaches to a barracks.
    - An eight-AI skirmish runs nine minutes with no error in the log.
    - Third wave: Nanocharge fires on one click from its add-on and rings
      both damaged Mastodons; a Syncronaut's bond attaches through its
      rider warhead; the Riot Trooper, the Rahn (a Clairvoyant dies, not
      mutates) and the Cryocopter's freeze stages work as under MO. Not
      played: the iron-curtain targeting (checked in Phobos' source:
      human-owned units skip iron-curtained targets when auto-targeting
      and retaliating) and the carriers' slower promotion (numbers only).
    - Fourth wave, each against `default`: a Siege Cadre fires at an idle
      refinery (idle under MO); with its Raccoon beam made an EMP, a
      Catastrophe's conscript falls silent (it kills three GIs under MO);
      the Megalodon's blade and the Suppressor's mark land as under MO;
      one Backwarp heals two Catastrophes from 1% to full, so all five
      pulses land; Deploy on GIs and an MCV sandbags the GIs and leaves
      the MCV packed. Not played: radiation credit and the Golden Wind.
    - With the AI superweapons charged at start (test-only), the AI fires
      Instant Shelter, the Repair Drone and the Sweeper Drop under
      `enhance` and none of them under `default`, and `Area Guard` parses.
      Not seen: the Sweepers deploying (Phobos' own auto-deploy uses the
      same Unload mission), the Decoy Squadron (its team did not form in
      time), naval mines (the map has no water) and Kingsnakes (US only).
    - Shelters and drones around the base: a Russian Mental AI aiming
      both at its base centre had about ten shelters ringing its war
      factory 46 minutes into a four-player game. Aiming them with
      `DropPod`, two games against the USA show its shelters spread
      over the outer base and the ground around the war factory open.
      It fired Instant Shelter 10 and 5 times, and in the second game,
      the one with the drones on `DropPod` too, the drone powers 8
      times, so the constraint and the paradrop work with that
      targeting. Not singled out on screen: the drones themselves.
    - Fifth wave: Hijackers the AI drops on a human base steal one of four
      parked tanks, which shells its old owner's Construction Yard, and
      bomb the rest. Quick Forts the AI drops when attacked stay empty:
      in three minutes it dropped three ($1500) while its bunker teams
      put one Lasher into a built bunker, so Quick Fort stays
      player-only (no Phobos trigger condition can tell an empty fort
      from a manned one to send a team promptly). Over a Tick Trap
      tunnel's life the AI spawns 8 ticks under `enhance` and 6 under
      `default`. Confused Rhinos open fire where they stand. In `default`,
      a V3 missile now comes down on a Rhino driving past (under Phobos'
      cell aim it burst on ground the Rhino had left), and the Harrier's
      armour mark still lands under Phobos, so it needs no rule. With
      four Grumbles deployed far from a small AI base, the AI's Instant
      Shelter lands beside its Construction Yard under `enhance` and out
      of the base under `default`. An AI Adept captures a player's Thor
      and the AI logs it as its own copy ("Thor Gunship (AI)"); a
      player's Adept turns an AI Thor into the player's Thor. Not
      played: the cloak restore (a scene could not get passengers to
      pick targets of their own; the hook reads the key as described),
      the Zorb lift and the miners' area guard (read in Phobos'
      source).
  - It changes gameplay, so online games need every player on `enhance`.

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

## Layer Layout

A layer mirrors the game directory (`src/mentara/layout.py` reads it). Every
file either supplies the file at its own path or, through one of three kinds
of structural names, changes something below it:

| Name in a layer | Means |
|---|---|
| `<archive>.mix/` (directory) | MIX container: the files below are members of that archive; nested `<archive>.mix/` directories reach archives inside it |
| `<name>.patch.<format>` | a patch of the file it names, written in `<format>` |
| `<name>.patch.<format>/` (directory) | the same patch split into fragments `*.<format>`, applied in name order |

The patch's extension is its format:

| Format | Patches | Example |
|---|---|---|
| INI syntax: `ini`, `map`, `yrm`, `mpr`, `cfg`, `inj` | `<name>.<format>`, by section and key | `Resources/ClientDefinitions.patch.ini` |
| `mix` | the archive `<name>.mix`, merging its entries by MIX ID | `expandmo99.patch.mix` |
| `toml` | any text file `<name>`, by line edits | `MentalOmegaClient.exe.config.patch.toml` |

Patches and containers compose in layer order on top of the file below, and
the plan hides every patch, patch directory and container it consumes, so the
game folder shows only the result. Inside a container only nested archives
and patch directories may be subdirectories, and a patch directory holds only
fragments in its format; anything else stops the plan with an error.

### INI patches

```ini
; Comments start with ';'.
Root=1              ; above the first header: the root of sectionless files
[Settings]          ; edit [Settings], creating it if absent
Key=Value           ; set every Key line, or add one
-Key                ; delete every Key line
[Animations]
+=NEW_ANIM          ; add under the next free integer key
[-Obsolete]         ; delete the section
```

Each operation has one spelling: `+` adds, `-` removes. A section repeated
in the target (MO's `aimo.ini` has several) is edited in every copy, so the
result does not depend on which copy the engine reads; `[-X]` followed by
`[X]` replaces a duplicated definition with one clean copy. Comments,
spacing around `=` and CRLF line endings of the target are kept.

### TOML patches

An array of `[[edit]]` tables, applied in order. Every edit that looks for
text names it `match`, and every edit that adds text names it `content`:

```toml
[[edit]]
op = "replace"          # every occurrence of match becomes content
match = "Renderer=auto"
content = "Renderer=opengl"

[[edit]]
op = "insert_after"     # also insert_before: lines next to each match
match = "[Video]"
content = "; Managed by Mentara"

[[edit]]
op = "delete"           # every line containing match
match = "Obsolete="
required = false        # match ops fail when nothing matches, unless false

[[edit]]
op = "append"           # also prepend
content = "; end"
```

### Names of added objects

Objects a layer adds to the game's INI files are named
`<Layer><Subject><Role>`: the layer (`Phobos`, `Enhance`), the unit or
system they serve, and what they are. Where MO marks a kind by suffix, the
suffix stays: warheads end in `WH` and elite weapons in `E`. For example
`PhobosRing24` (selection ring of radius 24), `PhobosUnitHealthTeam`
(health readout shown to the team), `EnhanceOxidizerMark` (the Oxidizer's
mark effect), `EnhanceCyclopsClose` / `EnhanceCyclopsCloseE`
(MO's `CyclopsCannon` at close range) and `EnhanceNanofiberHealWH`. A name
is at most 24 characters, the length the engine keeps of a type's ID; Ares
reports a longer one as a fatal error and the truncated type loses its
section. Art IDs
of new shapes are the shape's file stem in upper case (`PHRANKV` draws
`phrankv.shp`). New AI IDs follow MO's form: a fresh one takes the prefix
`MNT` and MO's kind (`MNTTF01-G` task force, `MNTSC01-G` script,
`MNTTT01-G` team), and a country's copy of an MO entry adds the country's
code before `-G`, as MO's own Last Bastion twins do (`FOETT135LB-G`). The
codes are two letters from MO's country labels: US EU PA (USA, Euro,
Pacific), RU LA CH (Russia, Latin, China), PC SC HQ (PsiCorps, Scorpion,
HQ), HA CO LB (Haihead, Coronia, Last Bastion). The generated Mental AI
numbers its IDs with four digits, family then tier or variant
(`MNTTF0102RU-G` is Russia's tier-2 line, with team `MNTTT0102RU-G` and
trigger `MNTTR0102RU-G`): 01-03 lines (direct, flank, hunt), 04 line
with air, 05-06 siege, 07-11 blitz, feint, economy, power and stealth
raids, 12 pincer, 13 air strike, 14 feint and strike, 15 base watch
(1511 on, posts), 16
patrol, 17 tech guard, 18 sky guard, 19 superweapon snipe, 20-25
capture (a trigger per tech building), garrison, bunkers, bio reactor,
hijack, 26 spies, 27 drops (engineers from 2701, saboteurs from 2721,
rushes from 2741; five more by sea and ten more by air), 28 bridge
repair, 29 starve, 30-32 navy, 33 flotillas, 34 escorted siege, 35
Chronosphere, 36 Iron Curtain, 37 boost assaults, 38 blackout assault,
39 finishing hunt, 40 grid strike, 41 squadrons, 42 heroes, 43 forward
deployers (4351 on, emplaced at home), 44 bombers, 45 carriers (ten
numbers a carrier, one a crew), 46 strike groups, 47 charges, 48
charges under the Iron Curtain, 49 hero drops (4926 on by sea, 4951 on
by air), 50-59 counter triggers, 60-79 counter squads, 80 air support,
81 miner hunts, 82 air cover (80 to 82 share a craft's number with its
squadron), 83 interceptors, 84 landings (ten numbers a target, by
tier), 85 psychic assaults (8551 on, posts), 86 infantry companies, 87
specialists with armour, 88 support columns, 89 miner guard, 99 MCV. A grand line is
numbered 50 past its tier's line (`MNTTT0153RU-G`), and an air snipe 50
past the snipe by land (1951 on). A two-team call's own lead team carries the call's
number (`MNTTT1202RU-G` leads Russia's tier-2 pincer). A line, siege or
raid variant puts its rank in the third digit (`MNTTF0112RU-G` is the
second-best tier-2 line). Scripts are numbered by kind
(`MNTSC1000-G`), with the country code when they cast that country's
superweapons (`MNTSC1000RU-G`); a hero drop's is 72000 plus its
building's index (`MNTSC72052-G` for the nuclear silo), an air snipe's
73000 plus it, and a support column's 74000 plus the index of the
`[AITargetTypes]` list it joins. Their names take the
country's label where MO's name has the side's ("Last Bastion - Condor
Hunt" for "Foehn - Buzzard Hunt"), and a task force is named by its
members ("4 Condor"). A house list naming the owner and its allies is `team`.

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
- **MIX patches and containers** (see Layer Layout): `<stem>.patch.mix`
  merges an overlay `.mix` (plain or encrypted) onto `<stem>.mix` by 32-bit
  MIX ID, and an `<archive>.mix/` directory patches, adds or replaces members,
  down through nested archives (`ra2md.mix/localmd.mix/rulesmd.patch.ini`,
  `ra2md.mix/localmd.patch.mix`), in strict layer order.

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
