# USB Remote Power Switch Skill Pack

Skill pack for safe USB serial control of **Y2KB-037 USB Remote Power Switch**.

Official product page: https://products.y2kb.com/usb-remote-power-switch/v1/

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
- `tools/y2kb-powerctl/` CLI (Python + pyserial, minimal dependency)
- `examples/` for Linux, macOS, Windows
- Unit tests for argument parsing, dry-run safety, and JSON output

## Quick start
```bash
cd tools/y2kb-powerctl
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
y2kb-powerctl --list-ports
y2kb-powerctl status --port <PORT> --json
y2kb-powerctl on --port <PORT> --dry-run --json
```

## Safety defaults
- `--dry-run` by default
- Side-effect operations require explicit `--execute`
- Pre-execution status check and confirmation prompt
- Cycle command rate-limiting
