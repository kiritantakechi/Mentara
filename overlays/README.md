# Mentara Overlay Layers

Each subdirectory here represents an independent overlay layer stacked on top of
the original Mental Omega game directory.

## Included Layers

- `overlays/phobos/`: Upstream **Phobos `v0.5-alpha2`** (`Phobos.dll`,
  bundled `Syringe.exe` / SyringeEx `0.1.0.2`, `gamemd.edb`,
  `Syringe.LICENSE.txt`, and `Phobos.pdb` which is excluded from Git via
  `*.pdb` in `.gitignore`).
  - Source: https://github.com/Phobos-developers/Phobos/releases/tag/v0.5-alpha2
  - Stacked *below* `overlays/base` so local overrides in `overlays/base`
    always take precedence.
- `overlays/base/`: Your local custom INI / DLL overrides.

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
