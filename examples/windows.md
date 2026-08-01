# Windows Examples

Official product page: https://products.example.com/usb-remote-power-switch/v1/

## 1) Dry-run first (no write)
```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\usb-power-switch-ctl.cmd on --port COM3 --dry-run --json
```

## 2) Execute ON
```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\usb-power-switch-ctl.cmd on --port COM3 --execute
```

## 3) Verify status
```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\usb-power-switch-ctl.cmd status --port COM3 --json
```

## 4) Cycle (3-second wait)
```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
.\usb-power-switch-ctl.cmd power-cycle --port COM3 --wait 3 --execute
```

## Alternative: run as Python module
```powershell
cd C:\path\to\usb-remote-power-switch-skill-pack\tools\usb-power-switch-ctl
python -m usb_power_switch_ctl status --port COM3 --json
```
