from __future__ import annotations

import argparse
import errno
import glob
import importlib
import json
import math
import os
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, NoReturn, Sequence

try:
    import serial  # type: ignore[import-not-found,import-untyped]
    from serial.tools import list_ports  # type: ignore[import-not-found,import-untyped]
except Exception:  # pragma: no cover - exercised by environments without pyserial
    serial = None  # type: ignore[assignment]
    list_ports = None  # type: ignore[assignment]

APP_NAME = "usb-power-switch-powerctl"
LOG_FILE_ENV_VAR = "USB_POWER_SWITCH_LOG_FILE"
DEFAULT_BAUD = 9600
DEFAULT_WAIT_SECONDS = 3.0
DEFAULT_TIMEOUT_SECONDS = 1.0
DEFAULT_MIN_CYCLE_INTERVAL_SECONDS = 5.0

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_PORT = 2
EXIT_PROTOCOL = 3
EXIT_ABORTED = 4
EXIT_RATE_LIMIT = 5
EXIT_INTERNAL = 6

SIDE_EFFECT_COMMANDS = {"on", "off", "power-cycle"}
WIRE_COMMANDS = {"on": "1", "off": "0", "status": "s"}
KNOWN_PORT_HINTS = ("ch340", "ch341", "wch", "usb serial", "ttyusb", "ttyacm")

_fallback_log_dir: Path | None = None


@dataclass
class CandidatePort:
    device: str
    description: str = ""
    hwid: str = ""


@dataclass
class ActionEntry:
    step: str
    tx: str | None = None
    rx: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "step": self.step,
            "tx": self.tx,
            "rx": self.rx,
            "note": self.note,
        }


@dataclass
class CommandResult:
    command: str
    dry_run: bool
    port: str
    baud: int
    wait_seconds: float
    requested_at: datetime
    state_before: str | None
    state_after: str | None
    actions: list[ActionEntry]
    note: str | None = None

    def to_payload(
        self,
        *,
        ok: bool,
        exit_code: int,
        log_file: Path,
        error: dict[str, str] | None,
    ) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "ok": ok,
            "exit_code": exit_code,
            "command": self.command,
            "dry_run": self.dry_run,
            "read_only": self.command == "status",
            "port": self.port,
            "baud": self.baud,
            "wait_seconds": self.wait_seconds,
            "requested_at": to_rfc3339(self.requested_at),
            "state_before": self.state_before,
            "state_after": self.state_after,
            "actions": [entry.to_dict() for entry in self.actions],
            "note": self.note,
            "log_file": str(log_file),
            "audit_logged": None,
            "error": error,
        }


class PowerCtlError(Exception):
    def __init__(
        self,
        message: str,
        exit_code: int,
        error_code: str,
        *,
        result: CommandResult | None = None,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.error_code = error_code
        self.result = result


class PySerialTransport:
    def __init__(self, *, port: str, baud: int, timeout: float) -> None:
        if serial is None:
            raise PowerCtlError(
                "pyserial is required. Install with: pip install pyserial",
                EXIT_USAGE,
                "pyserial_missing",
            )
        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=baud,
                timeout=timeout,
                write_timeout=timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
            )
        except Exception as exc:
            raise PowerCtlError(
                f"Failed to open serial port {port}: {exc}",
                EXIT_PORT,
                "open_port_failed",
            ) from exc

    def exchange(self, tx: str) -> str:
        try:
            self._serial.write(tx.encode("ascii"))
            self._serial.flush()
            rx = self._serial.readline()
        except Exception as exc:
            raise PowerCtlError(
                f"Serial communication failed: {exc}",
                EXIT_PROTOCOL,
                "serial_io_failed",
            ) from exc
        if not rx:
            raise PowerCtlError(
                "No response from device (timeout)",
                EXIT_PROTOCOL,
                "device_timeout",
            )
        return rx.decode("utf-8", errors="replace").strip()

    def close(self) -> None:
        try:
            self._serial.close()
        except Exception:
            pass


class PowerCtlArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise PowerCtlError(
            "Invalid command-line arguments. Use --help for accepted values.",
            EXIT_USAGE,
            "invalid_arguments",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = PowerCtlArgumentParser(
        prog="usb-power-switch-ctl",
        description="Control USB Remote Power Switch over USB serial.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["on", "off", "power-cycle", "status"],
        help="Control command to run",
    )
    parser.add_argument(
        "--port",
        help="Serial port (e.g. COM3, /dev/ttyUSB0, /dev/cu.usbserial-xxxx)",
    )
    parser.add_argument(
        "--wait",
        type=finite_float,
        default=DEFAULT_WAIT_SECONDS,
        help=f"Wait seconds for power-cycle command (default: {DEFAULT_WAIT_SECONDS})",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=DEFAULT_BAUD,
        help=f"Baud rate (default: {DEFAULT_BAUD})",
    )
    parser.add_argument(
        "--timeout",
        type=finite_float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Read/write timeout seconds (default: {DEFAULT_TIMEOUT_SECONDS})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )
    dry_group = parser.add_mutually_exclusive_group()
    dry_group.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help=(
            "Plan without state-changing serial writes "
            "(default behavior; status remains read-only)"
        ),
    )
    dry_group.add_argument(
        "--execute",
        action="store_false",
        dest="dry_run",
        help="Execute write operation after checks and confirmation",
    )
    parser.set_defaults(dry_run=True)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt for side-effect commands",
    )
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="Show detected serial ports and exit",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Override log file path",
    )
    parser.add_argument(
        "--min-cycle-interval",
        type=finite_float,
        default=DEFAULT_MIN_CYCLE_INTERVAL_SECONDS,
        help=(
            "Minimum seconds between execute power-cycle commands "
            f"(default: {DEFAULT_MIN_CYCLE_INTERVAL_SECONDS})"
        ),
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None and not args.list_ports:
        parser.error("command is required unless --list-ports is used")
    if args.wait < 0:
        parser.error("--wait must be >= 0")
    if args.timeout <= 0:
        parser.error("--timeout must be > 0")
    if args.baud <= 0:
        parser.error("--baud must be > 0")
    if args.min_cycle_interval <= 0:
        parser.error("--min-cycle-interval must be > 0")
    return args


def parse_output_options(argv: Sequence[str]) -> tuple[bool, Path | None]:
    parser = PowerCtlArgumentParser(
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--log-file", type=Path)
    try:
        options, _ = parser.parse_known_args(argv)
    except PowerCtlError:
        return "--json" in argv, None
    return options.json, options.log_file


def finite_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a finite number") from exc
    if not math.isfinite(parsed):
        raise argparse.ArgumentTypeError("value must be finite")
    return parsed


def detect_ports() -> list[CandidatePort]:
    candidates: list[CandidatePort] = []
    if list_ports is not None:
        for info in list_ports.comports():
            candidates.append(
                CandidatePort(
                    device=info.device,
                    description=info.description or "",
                    hwid=info.hwid or "",
                )
            )
    else:
        for device in fallback_port_scan():
            candidates.append(CandidatePort(device=device, description="fallback-scan"))
    candidates.sort(key=port_sort_key)
    return candidates


def fallback_port_scan() -> list[str]:
    if os.name == "nt":
        return []
    if sys.platform == "darwin":
        patterns = ("/dev/cu.usb*", "/dev/tty.usb*")
    else:
        patterns = ("/dev/ttyUSB*", "/dev/ttyACM*")
    found: set[str] = set()
    for pattern in patterns:
        for path in glob.glob(pattern):
            found.add(path)
    return sorted(found)


def port_sort_key(candidate: CandidatePort) -> tuple[int, str]:
    text = " ".join(
        token.lower() for token in (candidate.device, candidate.description, candidate.hwid)
    )
    hint_hits = sum(1 for hint in KNOWN_PORT_HINTS if hint in text)
    return (-hint_hits, candidate.device)


def resolve_port(
    *,
    explicit_port: str | None,
    detect_ports_fn: Callable[[], list[CandidatePort]],
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> str:
    if explicit_port:
        return explicit_port
    candidates = detect_ports_fn()
    if not candidates:
        raise PowerCtlError(
            "No serial port candidates were detected. Specify --port explicitly.",
            EXIT_PORT,
            "port_not_found",
        )
    output_fn("Detected serial port candidates:")
    for index, candidate in enumerate(candidates, start=1):
        details = candidate.description.strip() or "n/a"
        output_fn(
            f"[{index}] {format_text_value(candidate.device)} - "
            f"{format_text_value(details)}"
        )
    if not sys.stdin.isatty():
        raise PowerCtlError(
            "Interactive selection is required. Re-run with --port <PORT>.",
            EXIT_ABORTED,
            "port_selection_required",
        )
    raw = input_fn("Select port number (or q to cancel): ").strip().lower()
    if raw in {"q", "quit", "exit"}:
        raise PowerCtlError("Port selection cancelled by user.", EXIT_ABORTED, "user_cancelled")
    try:
        selected_index = int(raw)
    except ValueError as exc:
        raise PowerCtlError(
            f"Invalid selection '{raw}'.",
            EXIT_ABORTED,
            "invalid_selection",
        ) from exc
    if selected_index < 1 or selected_index > len(candidates):
        raise PowerCtlError(
            f"Selection out of range: {selected_index}",
            EXIT_ABORTED,
            "selection_out_of_range",
        )
    return candidates[selected_index - 1].device


def confirm_execute(
    *,
    command: str,
    port: str,
    state_before: str | None,
    input_fn: Callable[[str], str],
) -> None:
    state_note = state_before or "unknown"
    if not sys.stdin.isatty():
        raise PowerCtlError(
            "Refusing to execute without interactive confirmation. Use --yes to override.",
            EXIT_ABORTED,
            "confirmation_required",
        )
    prompt = (
        f"Execute {format_text_value(command)} on {format_text_value(port)}? "
        f"current_state={format_text_value(state_note)} [y/N]: "
    )
    answer = input_fn(prompt).strip().lower()
    if answer not in {"y", "yes"}:
        raise PowerCtlError("Operation cancelled by user.", EXIT_ABORTED, "user_cancelled")


def exchange_with_action(
    transport: PySerialTransport,
    actions: list[ActionEntry],
    *,
    step: str,
    tx: str,
) -> str:
    entry = ActionEntry(step=step, tx=tx, note="attempted; no response")
    actions.append(entry)
    response = transport.exchange(tx)
    entry.rx = response
    entry.note = None
    return response


def query_state(transport: PySerialTransport, actions: list[ActionEntry], step: str) -> str:
    response = exchange_with_action(transport, actions, step=step, tx="s")
    return parse_state(response)


def parse_state(response: str) -> str:
    clean = response.strip()
    if clean == "1":
        return "on"
    if clean == "0":
        return "off"
    raise PowerCtlError(
        f"Unexpected state response: {response!r}",
        EXIT_PROTOCOL,
        "unexpected_state",
    )


def planned_actions(command: str, wait_seconds: float) -> list[ActionEntry]:
    if command == "on":
        return [ActionEntry(step="plan_on", tx="1", note="dry-run; no write")]
    if command == "off":
        return [ActionEntry(step="plan_off", tx="0", note="dry-run; no write")]
    if command == "power-cycle":
        return [
            ActionEntry(step="plan_cycle_off", tx="0", note="dry-run; no write"),
            ActionEntry(step="plan_cycle_wait", note=f"sleep {wait_seconds:.2f}s"),
            ActionEntry(step="plan_cycle_on", tx="1", note="dry-run; no write"),
        ]
    raise PowerCtlError(f"Unsupported command: {command}", EXIT_USAGE, "unsupported_command")


def predict_state_after(command: str, state_before: str | None) -> str | None:
    if command == "on":
        return "on"
    if command == "off":
        return "off"
    if command == "power-cycle":
        return "on"
    if command == "status":
        return state_before
    return None


def cycle_stamp_path() -> Path:
    """Return the stable, user-scoped state path for power-cycle rate limiting."""
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            root = Path(local_app_data)
        else:
            root = Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        state_home = os.environ.get("XDG_STATE_HOME")
        if state_home:
            root = Path(state_home)
        else:
            root = Path.home() / ".local" / "state"
    return root / APP_NAME / "last_cycle_epoch.txt"


def cycle_lock_path(stamp_file: Path) -> Path:
    return stamp_file.with_name(f"{stamp_file.name}.lock")


def prepare_private_state_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        directory.chmod(0o700)
    except OSError:
        pass


def acquire_cycle_lock(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    if os.name == "nt":
        lock_module = importlib.import_module("msvcrt")
        lock_module.locking(handle.fileno(), lock_module.LK_NBLCK, 1)
    else:
        lock_module = importlib.import_module("fcntl")
        lock_module.flock(
            handle.fileno(),
            lock_module.LOCK_EX | lock_module.LOCK_NB,
        )


def release_cycle_lock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        lock_module = importlib.import_module("msvcrt")
        lock_module.locking(handle.fileno(), lock_module.LK_UNLCK, 1)
    else:
        lock_module = importlib.import_module("fcntl")
        lock_module.flock(handle.fileno(), lock_module.LOCK_UN)


@contextmanager
def cycle_rate_lock(lock_file: Path) -> Iterator[None]:
    try:
        prepare_private_state_directory(lock_file.parent)
        handle = lock_file.open("a+b")
    except OSError as exc:
        raise PowerCtlError(
            f"Cannot open power-cycle safety state: {exc}",
            EXIT_INTERNAL,
            "cycle_state_unavailable",
        ) from exc

    try:
        try:
            acquire_cycle_lock(handle)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise PowerCtlError(
                    "Another power-cycle reservation is in progress.",
                    EXIT_RATE_LIMIT,
                    "cycle_reservation_busy",
                ) from exc
            raise PowerCtlError(
                f"Cannot lock power-cycle safety state: {exc}",
                EXIT_INTERNAL,
                "cycle_state_unavailable",
            ) from exc
        try:
            yield
        finally:
            release_cycle_lock(handle)
    finally:
        handle.close()


def enforce_cycle_rate_limit(
    *, stamp_file: Path, now_epoch: float, min_interval: float
) -> None:
    if not math.isfinite(now_epoch) or not math.isfinite(min_interval) or min_interval <= 0:
        raise PowerCtlError(
            "Invalid power-cycle rate-limit parameters.",
            EXIT_INTERNAL,
            "cycle_state_invalid",
        )
    if stamp_file.exists():
        previous = stamp_file.read_text(encoding="utf-8").strip()
        try:
            last_epoch = float(previous)
        except ValueError as exc:
            raise PowerCtlError(
                "Power-cycle safety state is corrupt.",
                EXIT_INTERNAL,
                "cycle_state_invalid",
            ) from exc
        if not math.isfinite(last_epoch):
            raise PowerCtlError(
                "Power-cycle safety state is not finite.",
                EXIT_INTERNAL,
                "cycle_state_invalid",
            )
        elapsed = now_epoch - last_epoch
        if elapsed < min_interval:
            raise PowerCtlError(
                (
                    "power-cycle rate limit hit: "
                    f"{elapsed:.2f}s elapsed, minimum is {min_interval:.2f}s"
                ),
                EXIT_RATE_LIMIT,
                "cycle_rate_limited",
            )


def write_cycle_stamp(stamp_file: Path, now_epoch: float) -> None:
    prepare_private_state_directory(stamp_file.parent)
    temp_path: Path | None = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{stamp_file.name}.",
            dir=stamp_file.parent,
        )
        temp_path = Path(temp_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(f"{now_epoch:.6f}")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temp_path.chmod(0o600)
        except OSError:
            pass
        os.replace(temp_path, stamp_file)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


@contextmanager
def reserve_cycle_rate_limit(
    *, stamp_file: Path, now_epoch: float, min_interval: float
) -> Iterator[None]:
    with cycle_rate_lock(cycle_lock_path(stamp_file)):
        enforce_cycle_rate_limit(
            stamp_file=stamp_file,
            now_epoch=now_epoch,
            min_interval=min_interval,
        )
        write_cycle_stamp(stamp_file=stamp_file, now_epoch=now_epoch)
        yield


def recover_cycle_on(
    transport: PySerialTransport,
    result: CommandResult,
) -> None:
    exchange_with_action(
        transport,
        result.actions,
        step="cycle_recovery_on",
        tx="1",
    )
    result.state_after = query_state(
        transport,
        result.actions,
        step="status_after_recovery",
    )
    if result.state_after != "on":
        raise PowerCtlError(
            (
                "Power-cycle recovery verification failed: "
                f"expected on, got {result.state_after}"
            ),
            EXIT_PROTOCOL,
            "cycle_recovery_failed",
            result=result,
        )


def default_log_file() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            root = Path(base)
        else:
            root = Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Logs"
    else:
        state_root = os.environ.get("XDG_STATE_HOME")
        if state_root:
            root = Path(state_root)
        else:
            root = Path.home() / ".local" / "state"
    return root / APP_NAME / "powerctl.log"


def fallback_log_file() -> Path:
    global _fallback_log_dir
    if _fallback_log_dir is None:
        _fallback_log_dir = Path(
            tempfile.mkdtemp(
                prefix=f"{APP_NAME}-",
                dir=tempfile.gettempdir(),
            )
        )
    return _fallback_log_dir / "powerctl.log"


def pick_log_file(cli_log_file: Path | None) -> Path:
    if cli_log_file is not None:
        preferred = cli_log_file
    else:
        from_env = os.environ.get(LOG_FILE_ENV_VAR)
        if from_env:
            preferred = Path(from_env).expanduser()
        else:
            preferred = default_log_file()
    return pick_writable_log_file(preferred)


def pick_writable_log_file(preferred: Path) -> Path:
    try:
        preferred.parent.mkdir(parents=True, exist_ok=True)
        with preferred.open("a", encoding="utf-8"):
            pass
        return preferred
    except OSError:
        pass

    try:
        fallback = fallback_log_file()
    except OSError:
        return preferred
    if fallback != preferred:
        try:
            fallback.parent.mkdir(parents=True, exist_ok=True)
            with fallback.open("a", encoding="utf-8"):
                pass
            return fallback
        except OSError:
            pass
    return preferred


def to_rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def append_jsonl_log(log_file: Path, payload: dict[str, object]) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing_mode = log_file.stat().st_mode
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(existing_mode):
            raise OSError(errno.EINVAL, "Audit log path must be a regular file")
    record = dict(payload)
    record["logged_at"] = to_rfc3339(datetime.now(timezone.utc))
    with log_file.open("a", encoding="utf-8") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise OSError(errno.EINVAL, "Audit log path must be a regular file")
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_jsonl_log_best_effort(
    log_file: Path,
    payload: dict[str, object],
) -> tuple[Path, bool]:
    payload_for_log = dict(payload)
    payload_for_log["log_file"] = str(log_file)
    payload_for_log["audit_logged"] = True
    try:
        append_jsonl_log(log_file, payload_for_log)
        return log_file, True
    except (OSError, UnicodeError):
        pass

    try:
        fallback = fallback_log_file()
    except (OSError, UnicodeError):
        return log_file, False
    if fallback == log_file:
        return log_file, False
    payload_for_log = dict(payload)
    payload_for_log["log_file"] = str(fallback)
    payload_for_log["audit_logged"] = True
    try:
        append_jsonl_log(fallback, payload_for_log)
        return fallback, True
    except (OSError, UnicodeError):
        pass
    return log_file, False


def run_command(
    args: argparse.Namespace,
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
    detect_ports_fn: Callable[[], list[CandidatePort]],
    transport_factory: Callable[..., PySerialTransport],
    now_fn: Callable[[], datetime],
) -> CommandResult:
    command = args.command
    if command is None:
        raise PowerCtlError("command is required", EXIT_USAGE, "missing_command")

    needs_connection = command == "status" or not args.dry_run
    selected_port = args.port
    if needs_connection:
        selected_port = resolve_port(
            explicit_port=args.port,
            detect_ports_fn=detect_ports_fn,
            input_fn=input_fn,
            output_fn=output_fn,
        )
    if selected_port is None:
        selected_port = "(not-selected)"

    try:
        result = CommandResult(
            command=command,
            dry_run=args.dry_run,
            port=selected_port,
            baud=args.baud,
            wait_seconds=args.wait,
            requested_at=now_fn(),
            state_before=None,
            state_after=None,
            actions=[],
        )

        if command == "status":
            transport = transport_factory(
                port=selected_port,
                baud=args.baud,
                timeout=args.timeout,
            )
            try:
                current = query_state(transport, result.actions, step="status")
                result.state_before = current
                result.state_after = current
                result.note = (
                    "read-only status query; serial query sent, "
                    "no state-changing write performed"
                )
            finally:
                transport.close()
            return result

        if args.dry_run:
            result.actions.extend(planned_actions(command, args.wait))
            result.state_after = predict_state_after(command, None)
            result.note = "dry-run mode; no serial writes were performed"
            return result

        transport = transport_factory(
            port=selected_port,
            baud=args.baud,
            timeout=args.timeout,
        )
        try:
            result.state_before = query_state(
                transport,
                result.actions,
                step="status_before",
            )
            if not args.yes:
                confirm_execute(
                    command=command,
                    port=selected_port,
                    state_before=result.state_before,
                    input_fn=input_fn,
                )

            if command == "power-cycle":
                stamp_file = cycle_stamp_path()
                with reserve_cycle_rate_limit(
                    stamp_file=stamp_file,
                    now_epoch=time.time(),
                    min_interval=args.min_cycle_interval,
                ):
                    try:
                        exchange_with_action(
                            transport,
                            result.actions,
                            step="cycle_off",
                            tx="0",
                        )
                        result.state_after = query_state(
                            transport,
                            result.actions,
                            step="status_cycle_off",
                        )
                        if result.state_after != "off":
                            raise PowerCtlError(
                                (
                                    "Power-cycle OFF verification failed: "
                                    f"expected off, got {result.state_after}"
                                ),
                                EXIT_PROTOCOL,
                                "cycle_off_verification_failed",
                                result=result,
                            )
                        result.actions.append(
                            ActionEntry(
                                step="cycle_wait",
                                note=f"sleep {args.wait:.2f}s",
                            )
                        )
                        time.sleep(args.wait)
                        exchange_with_action(
                            transport,
                            result.actions,
                            step="cycle_on",
                            tx="1",
                        )
                        result.state_after = query_state(
                            transport,
                            result.actions,
                            step="status_after",
                        )
                        expected_state = predict_state_after(
                            command,
                            result.state_before,
                        )
                        if result.state_after != expected_state:
                            raise PowerCtlError(
                                (
                                    f"State verification failed for {command}: "
                                    f"expected {expected_state}, "
                                    f"got {result.state_after}"
                                ),
                                EXIT_PROTOCOL,
                                "state_verification_failed",
                                result=result,
                            )
                    except (Exception, KeyboardInterrupt) as exc:
                        recovery_note: str
                        try:
                            recover_cycle_on(transport, result)
                            recovery_note = "recovery ON verified"
                        except (Exception, KeyboardInterrupt) as recovery_exc:
                            recovery_note = (
                                "recovery ON not verified: "
                                f"{type(recovery_exc).__name__}: {recovery_exc}"
                            )
                        result.note = (
                            "power-cycle did not complete normally; "
                            f"{recovery_note}"
                        )
                        if isinstance(exc, PowerCtlError):
                            exc.result = result
                            raise
                        if isinstance(exc, KeyboardInterrupt):
                            raise PowerCtlError(
                                "Power-cycle interrupted by user.",
                                EXIT_ABORTED,
                                "cycle_interrupted",
                                result=result,
                            ) from exc
                        raise PowerCtlError(
                            f"Power-cycle failed: {exc}",
                            EXIT_INTERNAL,
                            "internal_error",
                            result=result,
                        ) from exc
            else:
                control_error: PowerCtlError | None = None
                try:
                    exchange_with_action(
                        transport,
                        result.actions,
                        step=command,
                        tx=WIRE_COMMANDS[command],
                    )
                except PowerCtlError as exc:
                    control_error = exc

                try:
                    result.state_after = query_state(
                        transport,
                        result.actions,
                        step="status_after",
                    )
                except PowerCtlError as verification_error:
                    if control_error is None:
                        raise
                    result.note = (
                        "control write response failed; postcondition could not be "
                        f"verified: {verification_error}"
                    )
                    control_error.result = result
                    raise control_error from verification_error
                expected_state = predict_state_after(
                    command,
                    result.state_before,
                )
                if control_error is not None:
                    if result.state_after == expected_state:
                        result.note = (
                            "control write response failed; postcondition verified by "
                            "status query"
                        )
                    else:
                        result.note = (
                            "control write response failed; status query observed an "
                            f"unexpected state: expected {expected_state}, "
                            f"got {result.state_after}"
                        )
                    control_error.result = result
                    raise control_error
                if result.state_after != expected_state:
                    raise PowerCtlError(
                        (
                            f"State verification failed for {command}: "
                            f"expected {expected_state}, got {result.state_after}"
                        ),
                        EXIT_PROTOCOL,
                        "state_verification_failed",
                        result=result,
                    )
        finally:
            transport.close()

        return result
    except PowerCtlError as exc:
        if exc.result is None and "result" in locals():
            exc.result = result
        raise
    except Exception as exc:
        raise PowerCtlError(
            str(exc),
            EXIT_INTERNAL,
            "internal_error",
            result=result if "result" in locals() else None,
        ) from exc


def print_ports(
    *,
    args: argparse.Namespace,
    output_fn: Callable[[str], None],
    detect_ports_fn: Callable[[], list[CandidatePort]],
) -> int:
    ports = detect_ports_fn()
    payload = {
        "schema_version": "1.0",
        "ok": True,
        "exit_code": EXIT_OK,
        "command": "list-ports",
        "ports": [
            {
                "device": candidate.device,
                "description": candidate.description,
                "hwid": candidate.hwid,
            }
            for candidate in ports
        ],
        "log_file": str(args.log_file),
        "audit_logged": None,
    }
    used_log_file, audit_logged = append_jsonl_log_best_effort(args.log_file, payload)
    payload["log_file"] = str(used_log_file)
    payload["audit_logged"] = audit_logged
    if args.json:
        output_fn(json.dumps(payload, ensure_ascii=False))
    else:
        if not ports:
            output_fn("No serial ports detected.")
        else:
            output_fn("Detected serial ports:")
            for candidate in ports:
                description = candidate.description or "n/a"
                output_fn(
                    f"- {format_text_value(candidate.device)} "
                    f"({format_text_value(description)})"
                )
        output_fn(
            "log_file={log_file} audit_logged={audit_logged}".format(
                log_file=format_text_value(payload["log_file"]),
                audit_logged=payload["audit_logged"],
            )
        )
    return EXIT_OK


def format_text_result(payload: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append(
        (
            "ok={ok} exit_code={exit_code} command={command} "
            "dry_run={dry_run} read_only={read_only}"
        ).format(
            ok=payload.get("ok"),
            exit_code=payload.get("exit_code"),
            command=format_text_value(payload.get("command")),
            dry_run=payload.get("dry_run"),
            read_only=payload.get("read_only"),
        )
    )
    lines.append(
        "port={port} baud={baud} wait={wait}".format(
            port=format_text_value(payload.get("port")),
            baud=payload.get("baud"),
            wait=payload.get("wait_seconds"),
        )
    )
    lines.append(
        "state_before={before} state_after={after}".format(
            before=format_text_value(payload.get("state_before")),
            after=format_text_value(payload.get("state_after")),
        )
    )
    lines.append(
        "log_file={log_file} audit_logged={audit_logged}".format(
            log_file=format_text_value(payload.get("log_file")),
            audit_logged=payload.get("audit_logged"),
        )
    )
    note = payload.get("note")
    if note:
        lines.append(f"note={format_text_value(note)}")
    actions = payload.get("actions")
    if isinstance(actions, list):
        for action in actions:
            if isinstance(action, dict):
                lines.append(
                    "action step={step} tx={tx} rx={rx} note={note}".format(
                        step=format_text_value(action.get("step")),
                        tx=format_text_value(action.get("tx")),
                        rx=format_text_value(action.get("rx")),
                        note=format_text_value(action.get("note")),
                    )
                )
    error = payload.get("error")
    if error:
        lines.append(
            "error="
            + json.dumps(
                error,
                ensure_ascii=True,
                sort_keys=True,
            )
        )
    return "\n".join(lines)


def format_text_value(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    return str(value)


def emit_error_result(
    *,
    result: CommandResult,
    exc: PowerCtlError,
    log_file: Path,
    json_output: bool,
    error_fn: Callable[[str], None],
) -> int:
    payload = result.to_payload(
        ok=False,
        exit_code=exc.exit_code,
        log_file=log_file,
        error={
            "code": exc.error_code,
            "message": str(exc),
        },
    )
    used_log_file, audit_logged = append_jsonl_log_best_effort(log_file, payload)
    payload["log_file"] = str(used_log_file)
    payload["audit_logged"] = audit_logged
    if json_output:
        error_fn(json.dumps(payload, ensure_ascii=False))
    else:
        error_fn(format_text_result(payload))
    return exc.exit_code


def main(
    argv: Sequence[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    output_stream=None,
    error_stream=None,
    detect_ports_fn: Callable[[], list[CandidatePort]] = detect_ports,
    transport_factory: Callable[..., PySerialTransport] = PySerialTransport,
    now_fn: Callable[[], datetime] | None = None,
) -> int:
    if output_stream is None:
        output_stream = sys.stdout
    if error_stream is None:
        error_stream = sys.stderr

    def output_fn(text: str) -> None:
        print(text, file=output_stream)

    def error_fn(text: str) -> None:
        print(text, file=error_stream)

    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    json_output, requested_log_file = parse_output_options(raw_argv)

    try:
        args = parse_args(raw_argv)
    except PowerCtlError as exc:
        log_file = pick_log_file(requested_log_file)
        parse_error_result = CommandResult(
            command="unknown",
            dry_run=True,
            port="(unknown)",
            baud=DEFAULT_BAUD,
            wait_seconds=DEFAULT_WAIT_SECONDS,
            requested_at=now_fn(),
            state_before=None,
            state_after=None,
            actions=[],
        )
        return emit_error_result(
            result=parse_error_result,
            exc=exc,
            log_file=log_file,
            json_output=json_output,
            error_fn=error_fn,
        )
    args.log_file = pick_log_file(args.log_file)

    try:
        if args.list_ports:
            return print_ports(
                args=args,
                output_fn=output_fn,
                detect_ports_fn=detect_ports_fn,
            )

        result = run_command(
            args,
            input_fn=input_fn,
            output_fn=output_fn,
            detect_ports_fn=detect_ports_fn,
            transport_factory=transport_factory,
            now_fn=now_fn,
        )
        payload = result.to_payload(
            ok=True,
            exit_code=EXIT_OK,
            log_file=args.log_file,
            error=None,
        )
        used_log_file, audit_logged = append_jsonl_log_best_effort(args.log_file, payload)
        payload["log_file"] = str(used_log_file)
        payload["audit_logged"] = audit_logged
        if args.json:
            output_fn(json.dumps(payload, ensure_ascii=False))
        else:
            output_fn(format_text_result(payload))
        return EXIT_OK
    except PowerCtlError as exc:
        error_result = exc.result or CommandResult(
            command=args.command or "unknown",
            dry_run=args.dry_run,
            port=args.port or "(unknown)",
            baud=args.baud,
            wait_seconds=args.wait,
            requested_at=now_fn(),
            state_before=None,
            state_after=None,
            actions=[],
        )
        return emit_error_result(
            result=error_result,
            exc=exc,
            log_file=args.log_file,
            json_output=args.json,
            error_fn=error_fn,
        )
    except Exception as exc:  # pragma: no cover - defensive guard
        payload = {
            "schema_version": "1.0",
            "ok": False,
            "exit_code": EXIT_INTERNAL,
            "log_file": str(args.log_file),
            "audit_logged": False,
            "error": {
                "code": "internal_error",
                "message": str(exc),
            },
        }
        if args.json:
            error_fn(json.dumps(payload, ensure_ascii=True))
        else:
            error_fn(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        return EXIT_INTERNAL
