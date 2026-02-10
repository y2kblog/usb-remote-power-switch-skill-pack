# WSL2 Setup Guide for USB Remote Power Switch

This guide is for the case where:
- Codex (or your terminal) runs inside WSL2, and
- the Y2KB-037 USB remote power switch is plugged into the Windows host.

Without USB passthrough, WSL2 often cannot talk to the device directly.

## 1. Windows host setup (first time)

Open **Administrator PowerShell** on Windows.

Install `usbipd-win`:

```powershell
winget install --id dorssel.usbipd-win
```

List devices and find your USB serial adapter (for example CH340):

```powershell
usbipd list
```

Bind the device by BUSID:

```powershell
usbipd bind --busid <BUSID>
```

If you see this warning:

`Unknown USB filter 'edevmon' may be incompatible ...`

retry with:

```powershell
usbipd bind --busid <BUSID> --force
```

Attach to WSL:

```powershell
usbipd attach --wsl --busid <BUSID>
```

Note:
- `bind` is usually one-time per device identity.
- `attach` may be needed again after unplug/replug or reboot.

## 2. WSL2 side checks

In WSL2:

```bash
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

If nothing appears, the device is not attached to WSL yet.

Check Linux group membership:

```bash
id
```

If `dialout` is missing, add it:

```bash
sudo usermod -aG dialout "$USER"
```

Then restart WSL session (`wsl --shutdown` from Windows, then reopen WSL).

## 3. Install and validate CLI in WSL2

```bash
cd tools/y2kb-powerctl
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

Safe validation flow:

```bash
y2kb-powerctl --list-ports --json
y2kb-powerctl status --port /dev/ttyUSB0 --json --timeout 3
y2kb-powerctl on --port /dev/ttyUSB0 --dry-run --json
```

Optional (recommended for restricted/sandboxed environments):

```bash
export Y2KB_POWERCTL_LOG_FILE=/tmp/y2kb-powerctl.log
```

The CLI now falls back to a temp-directory log path automatically when the
default log path is not writable.

After read/status checks succeed, you can execute side-effect commands with
`--execute`.

## 4. Preflight helper

From repository root:

```bash
bash scripts/wsl2-preflight.sh
```

This script checks:
- WSL environment detection
- `dialout` membership
- `/dev/ttyUSB*` or `/dev/ttyACM*` visibility
- `y2kb-powerctl` availability
- non-side-effect `--list-ports` probe

## 5. Troubleshooting map

- `No serial ports detected.`
  - USB device is not attached to WSL.
  - Re-run `usbipd list` and `usbipd attach --wsl --busid <BUSID>` on Windows.

- `Permission denied: '/dev/ttyUSB0'`
  - User is not in `dialout`, or session was not restarted after group change.

- `error.code = device_timeout`
  - Port opens but the device does not respond.
  - Check cable (data-capable), physical connector, and that the remote control
    USB port on the device is used.

- `error.code = open_port_failed`
  - Wrong port, port disappeared, or in use by another process.

- `Permission denied` while writing log file
  - Set `Y2KB_POWERCTL_LOG_FILE=/tmp/y2kb-powerctl.log` and retry.
  - The CLI also attempts automatic temp-path fallback.
