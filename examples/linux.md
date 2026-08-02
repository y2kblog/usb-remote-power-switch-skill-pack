# Linux Examples

Protocol contract: `../docs/protocol.md`

## Shell note

Before these examples, run `python3 scripts/bootstrap.py` once from the
repository root. Use the bootstrap-created venv binary directly to avoid PATH
issues: `./.venv-linux/bin/usb-power-switch-ctl`.

## 1) Detect port first

```bash
cd tools/usb-power-switch-ctl
./.venv-linux/bin/usb-power-switch-ctl --list-ports --json
```

Pick the target serial port from the output (for example: `/dev/ttyUSB0`).

## 2) Dry-run first (no write)

```bash
cd tools/usb-power-switch-ctl
./.venv-linux/bin/usb-power-switch-ctl on --port /dev/ttyUSB0 --dry-run --json
```

## 3) Execute ON

```bash
cd tools/usb-power-switch-ctl
./.venv-linux/bin/usb-power-switch-ctl on --port /dev/ttyUSB0 --execute --yes --json
```

## 4) Verify status

```bash
cd tools/usb-power-switch-ctl
./.venv-linux/bin/usb-power-switch-ctl status --port /dev/ttyUSB0 --json --timeout 10
```

## 5) Execute OFF

```bash
cd tools/usb-power-switch-ctl
./.venv-linux/bin/usb-power-switch-ctl off --port /dev/ttyUSB0 --execute --yes --json
```

## 6) Cycle (3-second wait)

```bash
cd tools/usb-power-switch-ctl
./.venv-linux/bin/usb-power-switch-ctl power-cycle --port /dev/ttyUSB0 --wait 3 --execute --yes --json
```

## Alternative: run as Python module

```bash
cd tools/usb-power-switch-ctl
./.venv-linux/bin/python -m usb_power_switch_ctl status --port /dev/ttyUSB0 --json
```
