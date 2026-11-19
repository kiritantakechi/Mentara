# Mentara Overlay Layers

Each subdirectory here represents an independent overlay layer stacked on top of
the original Mental Omega game directory.

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
