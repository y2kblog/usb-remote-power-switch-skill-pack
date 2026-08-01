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

## Repository protocol contract
- Verification status and exact accepted responses: `docs/protocol.md`
- USB serial settings enforced by the CLI: `9600 8N1`
- Command line ending: no newline
- Do not claim compatibility with a product variant until its manual and hardware
  behavior have been checked against `docs/protocol.md`.

## Safety rules (mandatory)
1. Use CLI only. Do not send raw serial bytes directly from free-form prompts.
2. Default to `--dry-run` (already default behavior).
3. For side-effect commands (`on`, `off`, `power-cycle`):
   - read current state first
   - require interactive confirmation unless `--yes` is explicitly set
   - verify the expected state after every state change
4. Keep power-cycle operations rate-limited (default minimum interval: 5s);
   the interval must be finite and greater than zero.
5. If port is not specified, show candidates and require explicit selection.
6. Use full option names. Abbreviated long options are rejected, especially for
   `--execute` and `--yes`.

## CLI location
- `tools/usb-power-switch-ctl/`

## CLI command
```bash
usb-power-switch-ctl on|off|power-cycle|status --port <PORT> [--wait 3] [--baud 9600] [--json] [--dry-run|--execute]
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
- `power-cycle` => CLI-composed sequence:
  `status -> off -> verify off -> wait -> on -> verify on`
- If a power-cycle fails after OFF is attempted, the CLI performs one ON recovery
  attempt, verifies the result, and still returns the original operation error.

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
- Input errors use exit code `1`; `--json` keeps them machine-readable.
- `dry_run=true` means no state-changing serial write. A `status` query is
  read-only and is also identified by `read_only=true`.
- Text output includes `log_file=<actual path>`, including when logging falls back to a temporary directory.
- Command results report `audit_logged=true` only after the JSONL audit record is written successfully; check for `false` before relying on the reported log path.
- Text output includes the result note and each attempted action so partial
  failures and recovery attempts remain visible without `--json`.
- Text values are escaped before display so serial responses cannot inject
  terminal control sequences or forged lines.
- Input-error messages do not echo raw invalid values into the audit log.

## Log path
- Linux: `~/.local/state/usb-power-switch-powerctl/powerctl.log` (`XDG_STATE_HOME` preferred)
- macOS: `~/Library/Logs/usb-power-switch-powerctl/powerctl.log`
- Windows: `%LOCALAPPDATA%\\usb-power-switch-powerctl\\powerctl.log`
- If default path is not writable, automatically falls back to a user-private temp subdirectory.
- Power-cycle rate-limit state uses the standard per-user state root (`XDG_STATE_HOME` on Linux and `LOCALAPPDATA` on Windows), but is stored separately and does not follow log-path changes.
- Rate-limit inspection and reservation are atomic, and an OS lock remains held
  until the power-cycle and its final verification or recovery complete.
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
