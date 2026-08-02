# Windows Examples

Protocol contract: `../docs/protocol.md`

## PowerShell note

Before these examples, run `py scripts\bootstrap.py` once from the repository
root (or use `python` if the Python launcher is unavailable). Use the
bootstrap-created executable directly to avoid PATH issues:
`.\.venv-windows\Scripts\usb-power-switch-ctl.exe`.

## 1) Detect port first

```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\.venv-windows\Scripts\usb-power-switch-ctl.exe --list-ports --json
```

Pick the target serial port from the output (for example: `COM6`).

## 2) Dry-run first (no write)

```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\.venv-windows\Scripts\usb-power-switch-ctl.exe on --port COM6 --dry-run --json
```

## 3) Execute ON

```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\.venv-windows\Scripts\usb-power-switch-ctl.exe on --port COM6 --execute --yes --json
```

## 4) Verify status

```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\.venv-windows\Scripts\usb-power-switch-ctl.exe status --port COM6 --json --timeout 10
```

## 5) Execute OFF

```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\.venv-windows\Scripts\usb-power-switch-ctl.exe off --port COM6 --execute --yes --json
```

## 6) Cycle (3-second wait)

```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\.venv-windows\Scripts\usb-power-switch-ctl.exe power-cycle --port COM6 --wait 3 --execute --yes --json
```

## Alternative: run as Python module

```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\.venv-windows\Scripts\python.exe -m usb_power_switch_ctl status --port COM6 --json
```
