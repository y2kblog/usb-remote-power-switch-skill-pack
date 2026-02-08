from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

try:
    import serial  # type: ignore[import-not-found]
    from serial.tools import list_ports  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - exercised by environments without pyserial
    serial = None  # type: ignore[assignment]
    list_ports = None  # type: ignore[assignment]

APP_NAME = "y2kb-powerctl"
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

SIDE_EFFECT_COMMANDS = {"on", "off", "cycle"}
WIRE_COMMANDS = {"on": "1", "off": "0", "status": "s"}
KNOWN_PORT_HINTS = ("ch340", "ch341", "wch", "usb serial", "ttyusb", "ttyacm")


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
            "port": self.port,
            "baud": self.baud,
            "wait_seconds": self.wait_seconds,
            "requested_at": to_rfc3339(self.requested_at),
            "state_before": self.state_before,
            "state_after": self.state_after,
            "actions": [entry.to_dict() for entry in self.actions],
            "note": self.note,
            "log_file": str(log_file),
            "error": error,
        }


class PowerCtlError(Exception):
    def __init__(self, message: str, exit_code: int, error_code: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.error_code = error_code


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="y2kb-powerctl",
        description="Control Y2KB USB Remote Power Switch over USB serial.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["on", "off", "cycle", "status"],
        help="Control command to run",
    )
    parser.add_argument(
        "--port",
        help="Serial port (e.g. COM3, /dev/ttyUSB0, /dev/cu.usbserial-xxxx)",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=DEFAULT_WAIT_SECONDS,
        help=f"Wait seconds for cycle command (default: {DEFAULT_WAIT_SECONDS})",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=DEFAULT_BAUD,
        help=f"Baud rate (default: {DEFAULT_BAUD})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
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
        help="Plan command without writing to device (default behavior)",
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
        type=float,
        default=DEFAULT_MIN_CYCLE_INTERVAL_SECONDS,
        help=(
            "Minimum seconds between execute cycle commands "
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
    if args.min_cycle_interval < 0:
        parser.error("--min-cycle-interval must be >= 0")
    return args


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
        output_fn(f"[{index}] {candidate.device} - {details}")
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
        f"Execute '{command}' on {port}? current_state={state_note} [y/N]: "
    )
    answer = input_fn(prompt).strip().lower()
    if answer not in {"y", "yes"}:
        raise PowerCtlError("Operation cancelled by user.", EXIT_ABORTED, "user_cancelled")


def query_state(transport: PySerialTransport, actions: list[ActionEntry], step: str) -> str:
    response = transport.exchange("s")
    actions.append(ActionEntry(step=step, tx="s", rx=response))
    return parse_state(response)


def parse_state(response: str) -> str:
    clean = response.strip()
    if clean.startswith("1"):
        return "on"
    if clean.startswith("0"):
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
    if command == "cycle":
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
    if command == "cycle":
        return "on"
    if command == "status":
        return state_before
    return None


def cycle_stamp_path(log_file: Path) -> Path:
    return log_file.parent / "last_cycle_epoch.txt"


def enforce_cycle_rate_limit(
    *, stamp_file: Path, now_epoch: float, min_interval: float
) -> None:
    if min_interval <= 0:
        return
    if stamp_file.exists():
        previous = stamp_file.read_text(encoding="utf-8").strip()
        if previous:
            try:
                last_epoch = float(previous)
            except ValueError:
                last_epoch = 0.0
            elapsed = now_epoch - last_epoch
            if elapsed < min_interval:
                raise PowerCtlError(
                    (
                        "cycle rate limit hit: "
                        f"{elapsed:.2f}s elapsed, minimum is {min_interval:.2f}s"
                    ),
                    EXIT_RATE_LIMIT,
                    "cycle_rate_limited",
                )


def write_cycle_stamp(stamp_file: Path, now_epoch: float) -> None:
    stamp_file.parent.mkdir(parents=True, exist_ok=True)
    stamp_file.write_text(f"{now_epoch:.6f}", encoding="utf-8")


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


def to_rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def append_jsonl_log(log_file: Path, payload: dict[str, object]) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    record = dict(payload)
    record["logged_at"] = to_rfc3339(datetime.now(timezone.utc))
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


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

    requested_at = now_fn()
    actions: list[ActionEntry] = []

    if command == "status":
        transport = transport_factory(port=selected_port, baud=args.baud, timeout=args.timeout)
        try:
            current = query_state(transport, actions, step="status")
        finally:
            transport.close()
        return CommandResult(
            command=command,
            dry_run=args.dry_run,
            port=selected_port,
            baud=args.baud,
            wait_seconds=args.wait,
            requested_at=requested_at,
            state_before=current,
            state_after=current,
            actions=actions,
        )

    if args.dry_run:
        actions.extend(planned_actions(command, args.wait))
        return CommandResult(
            command=command,
            dry_run=True,
            port=selected_port,
            baud=args.baud,
            wait_seconds=args.wait,
            requested_at=requested_at,
            state_before=None,
            state_after=predict_state_after(command, None),
            actions=actions,
            note="dry-run mode; no serial writes were performed",
        )

    transport = transport_factory(port=selected_port, baud=args.baud, timeout=args.timeout)
    try:
        state_before = query_state(transport, actions, step="status_before")
        if not args.yes:
            confirm_execute(
                command=command,
                port=selected_port,
                state_before=state_before,
                input_fn=input_fn,
            )

        if command == "cycle":
            stamp_file = cycle_stamp_path(args.log_file)
            now_epoch = time.time()
            enforce_cycle_rate_limit(
                stamp_file=stamp_file,
                now_epoch=now_epoch,
                min_interval=args.min_cycle_interval,
            )
            rx_off = transport.exchange("0")
            actions.append(ActionEntry(step="cycle_off", tx="0", rx=rx_off))
            actions.append(ActionEntry(step="cycle_wait", note=f"sleep {args.wait:.2f}s"))
            time.sleep(args.wait)
            rx_on = transport.exchange("1")
            actions.append(ActionEntry(step="cycle_on", tx="1", rx=rx_on))
            write_cycle_stamp(stamp_file=stamp_file, now_epoch=now_epoch)
        else:
            tx = WIRE_COMMANDS[command]
            rx = transport.exchange(tx)
            actions.append(ActionEntry(step=command, tx=tx, rx=rx))

        state_after = query_state(transport, actions, step="status_after")
    finally:
        transport.close()

    return CommandResult(
        command=command,
        dry_run=False,
        port=selected_port,
        baud=args.baud,
        wait_seconds=args.wait,
        requested_at=requested_at,
        state_before=state_before,
        state_after=state_after,
        actions=actions,
    )


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
    }
    if args.json:
        output_fn(json.dumps(payload, ensure_ascii=False))
    else:
        if not ports:
            output_fn("No serial ports detected.")
        else:
            output_fn("Detected serial ports:")
            for candidate in ports:
                description = candidate.description or "n/a"
                output_fn(f"- {candidate.device} ({description})")
    return EXIT_OK


def format_text_result(payload: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append(
        "ok={ok} exit_code={exit_code} command={command} dry_run={dry_run}".format(
            ok=payload.get("ok"),
            exit_code=payload.get("exit_code"),
            command=payload.get("command"),
            dry_run=payload.get("dry_run"),
        )
    )
    lines.append(
        "port={port} baud={baud} wait={wait}".format(
            port=payload.get("port"),
            baud=payload.get("baud"),
            wait=payload.get("wait_seconds"),
        )
    )
    lines.append(
        "state_before={before} state_after={after}".format(
            before=payload.get("state_before"),
            after=payload.get("state_after"),
        )
    )
    error = payload.get("error")
    if error:
        lines.append(f"error={error}")
    return "\n".join(lines)


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
    output_fn = lambda text: print(text, file=output_stream)
    error_fn = lambda text: print(text, file=error_stream)

    now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    args = parse_args(argv)
    args.log_file = args.log_file or default_log_file()

    if args.list_ports:
        return print_ports(args=args, output_fn=output_fn, detect_ports_fn=detect_ports_fn)

    try:
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
        append_jsonl_log(args.log_file, payload)
        if args.json:
            output_fn(json.dumps(payload, ensure_ascii=False))
        else:
            output_fn(format_text_result(payload))
        return EXIT_OK
    except PowerCtlError as exc:
        fallback = CommandResult(
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
        payload = fallback.to_payload(
            ok=False,
            exit_code=exc.exit_code,
            log_file=args.log_file,
            error={
                "code": exc.error_code,
                "message": str(exc),
            },
        )
        append_jsonl_log(args.log_file, payload)
        if args.json:
            error_fn(json.dumps(payload, ensure_ascii=False))
        else:
            error_fn(format_text_result(payload))
        return exc.exit_code
    except Exception as exc:  # pragma: no cover - defensive guard
        payload = {
            "schema_version": "1.0",
            "ok": False,
            "exit_code": EXIT_INTERNAL,
            "error": {
                "code": "internal_error",
                "message": str(exc),
            },
        }
        if args.json:
            error_fn(json.dumps(payload, ensure_ascii=False))
        else:
            error_fn(str(payload))
        return EXIT_INTERNAL

