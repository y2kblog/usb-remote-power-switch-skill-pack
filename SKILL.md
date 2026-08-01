---
name: usb-remote-power-switch
description: Safely operate the USB Remote Power Switch over USB serial using the bundled CLI (usb-power-switch-ctl), with dry-run by default and explicit confirmation for side-effect actions.
---

# USB Remote Power Switch Skill

## Scope
- Device: USB Remote Power Switch
- Transport: USB serial only
- Main operations: `on`, `off`, `power-cycle`, `status`

## Why this skill exists
This skill avoids fragile “raw serial text” operations by routing all control
through a deterministic CLI.

## Primary source references
- Official product page: https://products.example.com/usb-remote-power-switch/v1/
- USB serial settings from the source docs: `9600 8N1`
- Command line ending: no newline required

## Safety rules (mandatory)
1. Use CLI only. Do not send raw serial bytes directly from free-form prompts.
2. Default to `--dry-run` (already default behavior).
3. For side-effect commands (`on`, `off`, `power-cycle`):
   - read current state first
   - require interactive confirmation unless `--yes` is explicitly set
4. Keep power-cycle operations rate-limited (default minimum interval: 5s).
5. If port is not specified, show candidates and require explicit selection.

## CLI location
- `tools/usb-power-switch-ctl/`

## CLI command
```bash
usb-power-switch-ctl on|off|power-cycle|status --port <PORT> [--wait 3] [--baud 9600] [--json] [--dry-run]
```

## Canonical operation flow
1. Detect ports:
   - `usb-power-switch-ctl --list-ports`
2. Plan (no side effect):
   - `usb-power-switch-ctl on --port <PORT> --dry-run --json`
3. Execute:
   - `usb-power-switch-ctl on --port <PORT> --execute`
4. Verify:
   - `usb-power-switch-ctl status --port <PORT> --json`

## Command mapping
- `on` => serial command `1`
- `off` => serial command `0`
- `status` => serial command `s`
- `power-cycle` => CLI-composed sequence: `off -> wait -> on`

## Exit codes
- `0`: success
- `1`: usage/input error
- `2`: serial port error (not found/open failed)
- `3`: protocol/communication error
- `4`: user aborted / confirmation not provided
- `5`: power-cycle rate-limit violation
- `6`: unexpected internal error

## Output behavior
- Success:
  - text mode: stdout
  - JSON mode (`--json`): stdout JSON
- Error:
  - text mode: stderr
  - JSON mode (`--json`): stderr JSON
- Text output includes `log_file=<actual path>`, including when logging falls back to a temporary directory.

## Log path
- Linux: `~/.local/state/usb-power-switch-powerctl/powerctl.log` (`XDG_STATE_HOME` preferred)
- macOS: `~/Library/Logs/usb-power-switch-powerctl/powerctl.log`
- Windows: `%LOCALAPPDATA%\\usb-power-switch-powerctl\\powerctl.log`
- If default path is not writable, automatically falls back to a user-private temp subdirectory.
- Power-cycle rate-limit state uses the standard per-user state root (`XDG_STATE_HOME` on Linux and `LOCALAPPDATA` on Windows), but is stored separately and does not follow log-path changes.
- Optional override for all commands: `USB_POWER_SWITCH_LOG_FILE`

## Troubleshooting
- CH340/CH341 not detected:
  - verify cable supports data (not power-only)
  - check OS device listing tools
  - install CH340/CH341 driver if needed
- Permission denied on Linux:
  - check serial group permissions (`dialout`, etc.)
- No response:
  - ensure `9600 8N1`
  - confirm remote-control USB connector is used
  - avoid newline-terminated raw commands

## Examples
- `examples/linux.md`
- `examples/macos.md`
- `examples/windows.md`
