# USB Remote Power Switch Skill Pack

Skill pack for safe USB serial control of **USB Remote Power Switch**.

Official product page: https://products.example.com/usb-remote-power-switch/v1/

## WSL2 first-time setup (recommended)
If Codex is running in WSL2 and the device is plugged into the Windows host,
set up USB passthrough first so the serial device appears as `/dev/ttyUSB*` or
`/dev/ttyACM*` in Linux.

1. On Windows (Administrator PowerShell), install and configure `usbipd-win`.
2. Attach the CH340/USB serial device to WSL.
3. Run preflight checks from this repository:
   ```bash
   bash scripts/wsl2-preflight.sh
   ```

Detailed guide: `docs/wsl2-setup.md`

## Included
- `SKILL.md` for Codex / Claude Code skill usage
- `tools/usb-power-switch-ctl/` CLI (Python + pyserial, minimal dependency)
- `examples/` for Linux, macOS, Windows
- Unit tests for argument parsing, dry-run safety, and JSON output

## Quick start
```bash
cd tools/usb-power-switch-ctl
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
usb-power-switch-ctl --list-ports
usb-power-switch-ctl status --port <PORT> --json
usb-power-switch-ctl on --port <PORT> --dry-run --json
```

## Safety defaults
- `--dry-run` by default
- Side-effect operations require explicit `--execute`
- Pre-execution status check and confirmation prompt
- Power-cycle command rate-limiting
- If default log path is not writable, logging falls back to a user-private temp subdirectory
- Power-cycle rate-limit state is stored separately in a fixed per-user state path

## Log path override
- You can pin the log path for all commands with `USB_POWER_SWITCH_LOG_FILE`.
- Use a path inside a user-owned private directory; do not use a predictable file in a shared temporary directory.
- If the variable is unset and the default path is unwritable, the CLI automatically uses a user-private temporary subdirectory.
