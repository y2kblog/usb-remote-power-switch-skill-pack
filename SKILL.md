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

## Setup before operation
1. Confirm that the complete skill pack, not `SKILL.md` alone, is available in
   the active skill directory. The bundled CLI, protocol contract, examples,
   and bootstrap script are required.
2. Before the first operation, run the following from the skill-pack root:
   ```bash
   python3 scripts/bootstrap.py
   ```
   On Windows, use `py scripts\bootstrap.py` when available, otherwise
   `python scripts\bootstrap.py`.
3. Bootstrap creates or reuses an operating-system-specific venv, installs the
   CLI, and performs only `--list-ports --json`. The defaults are
   `.venv-linux` for Linux/WSL2, `.venv-macos` for macOS, and `.venv-windows`
   for Windows under `tools/usb-power-switch-ctl/`. It must not select a port,
   request elevated access, attach USB devices to WSL2, or send a
   state-changing command. Do not reuse one operating system's venv from
   another operating system.
4. Use the bootstrap-created CLI directly: on Linux/WSL2,
   `tools/usb-power-switch-ctl/.venv-linux/bin/usb-power-switch-ctl`; on macOS,
   `tools/usb-power-switch-ctl/.venv-macos/bin/usb-power-switch-ctl`; on Windows,
   `tools\usb-power-switch-ctl\.venv-windows\Scripts\usb-power-switch-ctl.exe`.
   Substitute that exact operating-system-specific path for `<CLI>` in the
   commands below.
   Do not fall back to raw serial commands or an arbitrary PATH command when
   setup is incomplete.
5. To install from a source checkout into a user or repository skill location,
   use `scripts/bootstrap.py --install-to <new-absolute-skill-directory>`.
   The directory must be explicitly chosen and absent; if it already exists,
   stop and report it rather than overwriting the existing skill. See
   `README.md` for the Codex and Claude Code locations.

## CLI command
```bash
<CLI> on|off|power-cycle|status --port <PORT> [--wait 3] [--baud 9600] [--json] [--dry-run|--execute]
```

## Canonical operation flow
0. Bootstrap and inspect its non-side-effect port-list result. If no candidates
   are found, stop and diagnose USB visibility, permissions, or WSL2 passthrough.
   If multiple candidates are found, require explicit user selection.
1. Detect ports:
   - `<CLI> --list-ports`
2. Plan (no side effect):
   - `<CLI> on --port <PORT> --dry-run --json`
3. Execute:
   - `<CLI> on --port <PORT> --execute`
4. Verify:
   - `<CLI> status --port <PORT> --json`

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
