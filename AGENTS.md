# AGENTS.md

This repository is a skill pack for controlling a USB remote power switch via USB serial.

## Goal
- Keep side-effectful power actions safe and deterministic.
- Prefer CLI execution over free-form serial operations.

## Structure
- `SKILL.md`: main skill contract
- `examples/`: OS-specific command examples
- `tools/usb-power-switch-ctl/`: bundled control CLI and tests

## Setup
```bash
cd tools/usb-power-switch-ctl
python3 -m pip install -e .
```

If editable install is not desired:
```bash
cd tools/usb-power-switch-ctl
python3 -m pip install pyserial
```

## Validate
```bash
cd tools/usb-power-switch-ctl
python3 -m unittest discover -s tests -v
```

## Safe execution baseline
1. `usb-power-switch-ctl --list-ports`
2. `usb-power-switch-ctl status --port <PORT> --json`
3. `usb-power-switch-ctl on --port <PORT> --dry-run --json`
4. `usb-power-switch-ctl on --port <PORT> --execute`
5. `usb-power-switch-ctl status --port <PORT> --json`

## Safety invariants
- `--dry-run` is default.
- `on/off/power-cycle` require explicit `--execute` to write.
- State is read before side-effect commands.
- Interactive confirmation is required unless `--yes`.
- `power-cycle` is rate-limited by default.
