set shell := ["bash", "-euo", "pipefail", "-c"]

# Show available recipes.
default:
    @just --list

# Sync virtual environment and all dependency groups via uv.
sync:
    uv sync --all-groups

# Launch Mental Omega using the selected profile (default: "default").
launch profile="default" *args:
    uv run mentara launch --profile {{profile}} {{args}}

# Preview the resolved layers, virtual paths, and launch command without running.
dry-run profile="default" *args:
    uv run mentara launch --profile {{profile}} --dry-run {{args}}

# Mount or stage the virtual directory persistently without launching the game.
mount profile="default" *args:
    uv run mentara mount --profile {{profile}} {{args}}

# Unmount or tear down an active virtual directory for a profile.
unmount profile="default" *args:
    uv run mentara unmount --profile {{profile}} {{args}}

# Inspect resolved overlay files, shadowed layers, and case collisions.
inspect profile="default" *args:
    uv run mentara inspect --profile {{profile}} {{args}}

# Inspect only INI and DLL overrides across layers.
inspect-ini-dll profile="default":
    uv run mentara inspect --profile {{profile}} --filter '*.ini' --filter '*.dll'

# List all profiles declared in mentara.toml.
profiles:
    uv run mentara profiles

# Run environment and Mental Omega overlay diagnostics.
doctor profile="default" *args:
    uv run mentara doctor --profile {{profile}} {{args}}

# Create a new overlay layer scaffold under overlays/.
init-layer name:
    uv run mentara init-layer {{name}}

# Format Python source and tests with ruff.
fmt:
    uv run ruff format

# Verify formatting without modifying files.
fmt-check:
    uv run ruff format --check

# Run ruff static analysis.
lint:
    uv run ruff check

# Run strict static type checking with ty.
typecheck:
    uv run ty check

# Run the pytest test suite.
test *args:
    uv run pytest {{args}}

# Run pytest with coverage report.
cov:
    uv run pytest --cov=mentara --cov-report=term-missing

# Run the full quality gate: format check, lint, typecheck, and tests.
check: fmt-check lint typecheck test

# Build wheel and sdist using uv_build.
build:
    uv build
