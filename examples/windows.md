# Windows Examples

Protocol contract: `../docs/protocol.md`

## PowerShell note
In PowerShell, commands in the current directory are not auto-discovered.
Always run the wrapper with the `.\` prefix (for example:
`.\usb-power-switch-ctl.cmd`).

## 1) Detect port first
```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\usb-power-switch-ctl.cmd --list-ports --json
```
Pick the target serial port from the output (for example: `COM6`).

## 2) Dry-run first (no write)
```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\usb-power-switch-ctl.cmd on --port COM6 --dry-run --json
```

## 3) Execute ON
```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\usb-power-switch-ctl.cmd on --port COM6 --execute --yes --json
```

## 4) Verify status
```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\usb-power-switch-ctl.cmd status --port COM6 --json --timeout 10
```

## 5) Execute OFF
```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\usb-power-switch-ctl.cmd off --port COM6 --execute --yes --json
```

## 6) Cycle (3-second wait)
```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\usb-power-switch-ctl.cmd power-cycle --port COM6 --wait 3 --execute --yes --json
```

## Alternative: run as Python module
```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
python -m usb_power_switch_ctl status --port COM6 --json
```
