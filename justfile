[unix]
set shell := ["bash", "-euo", "pipefail", "-c"]

[windows]
set shell := ["pwsh", "-NoLogo", "-NoProfile", "-Command"]

# Show available recipes.
[default]
default:
    @just --list

# Sync virtual environment and all dependency groups via uv.
[group("dev")]
sync:
    uv sync --all-groups

# Launch Mental Omega using the selected profile (default: "default").
[group("launcher")]
launch profile="default" *args:
    uv run mentara launch --profile {{ profile }} {{ args }}

# Preview the resolved layers, virtual paths, and launch command without running.
[group("launcher")]
dry-run profile="default" *args:
    uv run mentara launch --profile {{ profile }} --dry-run {{ args }}

# Mount or stage the virtual directory persistently without launching the game.
[group("launcher")]
mount profile="default" *args:
    uv run mentara mount --profile {{ profile }} {{ args }}

# Unmount or tear down an active virtual directory for a profile.
[group("launcher")]
unmount profile="default" *args:
    uv run mentara unmount --profile {{ profile }} {{ args }}

# Remove persisted writable runtime state for a profile.
[group("launcher")]
clean profile="default" *args:
    uv run mentara clean --profile {{ profile }} {{ args }}

# Inspect resolved overlay files, patches, and case collisions.
[group("launcher")]
inspect profile="default" *args:
    uv run mentara inspect --profile {{ profile }} {{ args }}

# List all profiles declared in mentara.toml.
[group("launcher")]
profiles:
    uv run mentara profiles

# Run environment and Mental Omega overlay diagnostics.
[group("launcher")]
doctor profile="default" *args:
    uv run mentara doctor --profile {{ profile }} {{ args }}

# Format justfile, Python source, and tests.
[group("dev")]
fmt:
    just --unstable --fmt
    uv run ruff format

# Verify formatting of justfile and Python files without modifying them.
[group("dev")]
fmt-check:
    just --unstable --fmt --check
    uv run ruff format --check

# Run ruff static analysis.
[group("dev")]
lint:
    uv run ruff check

# Run strict static type checking with ty.
[group("dev")]
typecheck:
    uv run ty check

# Run the pytest test suite.
[group("dev")]
test *args:
    uv run pytest {{ args }}

# Run pytest with coverage report.
[group("dev")]
cov:
    uv run pytest --cov=mentara --cov-report=term-missing

# Run the full quality gate: format check, lint, typecheck, and tests.
[group("dev")]
check: fmt-check lint typecheck test

# Build generated layer files from assets/ (string tables, palettes, shapes, hook DLLs).
[group("dev")]
assets *args:
    uv run mentara assets {{ args }}

# Build wheel and sdist using uv_build.
[group("dev")]
build:
    uv build
