# USB Remote Power Switch Skill Pack


Skill pack for safe USB serial control of **USB Remote Power Switch**.
Official product page: https://products.y2kb.com/usb-remote-power-switch/v1/

Protocol contract and verification status: `docs/protocol.md`


## Agent-assisted first-time setup

This pack works on Linux, macOS, Windows, and WSL2 with Python 3.9 or later.
The bootstrap creates or reuses a local CLI virtual environment, installs the
single runtime dependency, and performs only the non-side-effect
`--list-ports --json` probe. A zero-port result is a successful setup with a
hardware, permission, or WSL2 follow-up; it never selects a port or writes to
the device.

### Install as an agent skill

Keep the complete repository together: `SKILL.md` relies on the bundled CLI,
protocol contract, examples, and bootstrap script. From a checked-out copy of
this repository, an agent or user can install it into a **new, explicit**
target directory with the commands below. The installer refuses an existing
target instead of replacing a skill or its virtual environment. Installed
copies include `.gitignore` for bootstrap-created virtual environments and
`.gitattributes` for LF-only shell scripts.

Codex user skill location (Linux/macOS):

```bash
python3 scripts/bootstrap.py --install-to "$HOME/.agents/skills/usb-remote-power-switch"
```

Codex user skill location (Windows PowerShell):

```powershell
py scripts\bootstrap.py --install-to (Join-Path $HOME '.agents\skills\usb-remote-power-switch')
```

Claude Code user skill location (Linux/macOS):

```bash
python3 scripts/bootstrap.py --install-to "$HOME/.claude/skills/usb-remote-power-switch"
```

Claude Code user skill location (Windows PowerShell):

```powershell
py scripts\bootstrap.py --install-to (Join-Path $HOME '.claude\skills\usb-remote-power-switch')
```

Codex also supports a repository-scoped location at
`<target-repository>/.agents/skills/usb-remote-power-switch/`; pass that full
new path to `--install-to` when the skill should apply only to that repository.
Codex normally detects the new skill automatically; restart it if the skill is
not listed by `/skills`. Claude Code may need a restart when its top-level
skills directory was created during installation. The locations follow the
[Codex skills guide](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)
and the [Claude Code skills guide](https://code.claude.com/docs/en/slash-commands#where-skills-live).

An agent may perform cloning, copying into a new target, bootstrap, and the
port-list probe. It must stop for physical USB connection, serial-port choice,
administrator approval, Linux group changes, WSL2 USB attachment, and every
`--execute` request.

### Use from an existing checkout

Run this once from the repository root when the pack is already in its final
skill directory or when using it directly:

```bash
python3 scripts/bootstrap.py
```

On Windows, use `py scripts\bootstrap.py` when the Python launcher is
available, or `python scripts\bootstrap.py` otherwise. The bootstrap keeps one
non-portable virtual environment per operating system:

| Environment | Default CLI environment |
| --- | --- |
| Linux and WSL2 | `tools/usb-power-switch-ctl/.venv-linux` |
| macOS | `tools/usb-power-switch-ctl/.venv-macos` |
| Windows | `tools/usb-power-switch-ctl/.venv-windows` |

For a checkout used on only one operating system, only that environment is
created. A checkout shared between Windows and WSL2 keeps both environments
separately, so neither side reuses or overwrites the other's venv. Bootstrap is
idempotent within each operating system. If the current operating system's
directory exists but does not contain a usable Python executable, bootstrap
stops rather than overwriting it; repair or remove only that directory
deliberately, then rerun the command. A generic `.venv` created by an earlier
revision is not reused automatically.

The repository enforces LF line endings for shell scripts through
`.gitattributes`, including on Windows checkouts. For WSL2 USB passthrough and
permission diagnostics, see `docs/wsl2-setup.md`.

## Included
- `SKILL.md` for Codex / Claude Code skill usage
- `tools/usb-power-switch-ctl/` CLI (Python + pyserial, minimal dependency)
- `examples/` for Linux, macOS, Windows
- Unit tests for argument parsing, dry-run safety, state verification, recovery,
  rate-limit concurrency, and JSON output

## Safe first operation (after bootstrap)
```bash
cd tools/usb-power-switch-ctl
./.venv-linux/bin/usb-power-switch-ctl --list-ports --json
./.venv-linux/bin/usb-power-switch-ctl status --port <PORT> --json
./.venv-linux/bin/usb-power-switch-ctl on --port <PORT> --dry-run --json
```

On macOS, replace `.venv-linux` with `.venv-macos`. On Windows, use
`tools\usb-power-switch-ctl\.venv-windows\Scripts\usb-power-switch-ctl.exe`.
Choose `<PORT>` explicitly from the port-list result. Typical names are
`/dev/ttyUSB*` or `/dev/ttyACM*` on Linux/WSL2, `/dev/tty.usbserial*` or
`/dev/tty.usbmodem*` on macOS, and `COMx` on Windows.

## Quality checks

Install the development tools and run the same local checks as CI:

```bash
cd tools/usb-power-switch-ctl
python -m pip install -e ".[dev]"
usb-power-switch-ctl --help
python -I -m unittest discover -s tests -v
python -m ruff check usb_power_switch_ctl tests ../../scripts/bootstrap.py
python -m mypy usb_power_switch_ctl ../../scripts/bootstrap.py
python -m coverage run -m unittest discover -s tests -v
python -m coverage report -m
python -m pip_audit . --progress-spinner off --strict
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
