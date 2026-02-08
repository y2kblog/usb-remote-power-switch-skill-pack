---
name: usb-remote-power-switch
description: Safely operate the Y2KB-037 USB Remote Power Switch over USB serial using the bundled CLI (y2kb-powerctl), with dry-run by default and explicit confirmation for side-effect actions.
---

# USB Remote Power Switch Skill

## Scope
- Device: Y2KB-037 USB Remote Power Switch
- Transport: USB serial only
- Main operations: `on`, `off`, `cycle`, `status`

## Why this skill exists
This skill avoids fragile “raw serial text” operations by routing all control
through a deterministic CLI.

## Primary source references
- Product page source: `content/usb-remote-power-switch/v1.md`
- Serial command spec: `static/doc/usb-remote-power-switch/v1/serial_command_ja.pdf`
- USB serial settings from the source docs: `9600 8N1`
- Command line ending: no newline required

## Safety rules (mandatory)
1. Use CLI only. Do not send raw serial bytes directly from free-form prompts.
2. Default to `--dry-run` (already default behavior).
3. For side-effect commands (`on`, `off`, `cycle`):
   - read current state first
   - require interactive confirmation unless `--yes` is explicitly set
4. Keep cycle operations rate-limited (default minimum interval: 5s).
5. If port is not specified, show candidates and require explicit selection.

## CLI location
- `tools/y2kb-powerctl/`

## CLI command
```bash
y2kb-powerctl on|off|cycle|status --port <PORT> [--wait 3] [--baud 9600] [--json] [--dry-run]
```

## Canonical operation flow
1. Detect ports:
   - `y2kb-powerctl --list-ports`
2. Plan (no side effect):
   - `y2kb-powerctl on --port <PORT> --dry-run --json`
3. Execute:
   - `y2kb-powerctl on --port <PORT> --execute`
4. Verify:
   - `y2kb-powerctl status --port <PORT> --json`

## Command mapping
- `on` => serial command `1`
- `off` => serial command `0`
- `status` => serial command `s`
- `cycle` => CLI-composed sequence: `off -> wait -> on`

## Exit codes
- `0`: success
- `1`: usage/input error
- `2`: serial port error (not found/open failed)
- `3`: protocol/communication error
- `4`: user aborted / confirmation not provided
- `5`: cycle rate-limit violation
- `6`: unexpected internal error

## Output behavior
- Success:
  - text mode: stdout
  - JSON mode (`--json`): stdout JSON
- Error:
  - text mode: stderr
  - JSON mode (`--json`): stderr JSON

## Log path
- Linux: `~/.local/state/y2kb-powerctl/powerctl.log` (`XDG_STATE_HOME` preferred)
- macOS: `~/Library/Logs/y2kb-powerctl/powerctl.log`
- Windows: `%LOCALAPPDATA%\\y2kb-powerctl\\powerctl.log`

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
