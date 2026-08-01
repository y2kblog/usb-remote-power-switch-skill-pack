# USB Remote Power Switch Skill Pack

Skill pack for safe USB serial control of **USB Remote Power Switch**.

Protocol contract and verification status: `docs/protocol.md`

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

The repository enforces LF line endings for shell scripts through
`.gitattributes`, including on Windows checkouts.

Detailed guide: `docs/wsl2-setup.md`

## Included
- `SKILL.md` for Codex / Claude Code skill usage
- `tools/usb-power-switch-ctl/` CLI (Python + pyserial, minimal dependency)
- `examples/` for Linux, macOS, Windows
- Unit tests for argument parsing, dry-run safety, state verification, recovery,
  rate-limit concurrency, and JSON output

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

## Quality checks

Install the development tools and run the same local checks as CI:

```bash
cd tools/usb-power-switch-ctl
python -m pip install -e ".[dev]"
usb-power-switch-ctl --help
python -I -m unittest discover -s tests -v
python -m ruff check usb_power_switch_ctl tests
python -m mypy usb_power_switch_ctl
python -m coverage run -m unittest discover -s tests -v
python -m coverage report -m
python -m pip_audit --progress-spinner off --strict
bash -n ../../scripts/wsl2-preflight.sh
```

CI runs the unit tests on Linux, Windows, and macOS with Python 3.9 and 3.13.
The quality job enforces source branch coverage of at least 70% and runs the
static, dependency, and shell syntax checks above.

## Safety defaults
- `--dry-run` by default for state-changing commands
- `status` sends only the read-only serial query and reports `read_only=true`
- Side-effect operations require explicit `--execute`
- Pre-execution status check, confirmation prompt, and postcondition verification
- Power-cycle verifies OFF before waiting and ON after the cycle
- Interrupted or failed power-cycle operations attempt one ON recovery and report
  both the original failure and recovery result
- Power-cycle rate-limiting cannot be disabled and concurrent cycles are locked
- If default log path is not writable, logging falls back to a user-private temp subdirectory
- Power-cycle rate-limit state is stored separately in a fixed per-user state path

Input errors use exit code `1`. With `--json`, input errors use the same structured
error payload and JSONL audit log as runtime errors.
Text output includes the result note and every attempted action, including
recovery attempts that did not receive a response.
Command results include `audit_logged=true` only when the JSONL audit record was
written to the reported primary or fallback `log_file`; otherwise they report
`audit_logged=false`.
Long options must be written in full; abbreviations such as `--e` for
`--execute` are rejected. Input-error audit records use a stable generic
message instead of copying raw invalid values.

## Log path override
- You can pin the log path for all commands with `USB_POWER_SWITCH_LOG_FILE`.
- Use a path inside a user-owned private directory; do not use a predictable file in a shared temporary directory.
- If the variable is unset and the default path is unwritable, the CLI automatically uses a user-private temporary subdirectory.
