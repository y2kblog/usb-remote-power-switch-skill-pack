# AGENTS.md

This repository is a skill pack for controlling Y2KB-037 via USB serial.

## Goal
- Keep side-effectful power actions safe and deterministic.
- Prefer CLI execution over free-form serial operations.

## Structure
- `SKILL.md`: main skill contract
- `examples/`: OS-specific command examples
- `tools/y2kb-powerctl/`: bundled control CLI and tests

## Setup
```bash
cd tools/y2kb-powerctl
python3 -m pip install -e .
```

If editable install is not desired:
```bash
cd tools/y2kb-powerctl
python3 -m pip install pyserial
```

## Validate
```bash
cd tools/y2kb-powerctl
python3 -m unittest discover -s tests -v
```

## Safe execution baseline
1. `y2kb-powerctl --list-ports`
2. `y2kb-powerctl status --port <PORT> --json`
3. `y2kb-powerctl on --port <PORT> --dry-run --json`
4. `y2kb-powerctl on --port <PORT> --execute`
5. `y2kb-powerctl status --port <PORT> --json`

## Safety invariants
- `--dry-run` is default.
- `on/off/power-cycle` require explicit `--execute` to write.
- State is read before side-effect commands.
- Interactive confirmation is required unless `--yes`.
- `power-cycle` is rate-limited by default.
