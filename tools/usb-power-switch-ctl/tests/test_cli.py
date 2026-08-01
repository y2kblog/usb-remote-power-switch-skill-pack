from __future__ import annotations

import io
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from unittest import mock

from usb_power_switch_ctl import cli


FIXED_NOW = datetime(2026, 2, 8, 0, 0, tzinfo=timezone.utc)


class FakeTransport:
    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = list(responses)
        self.writes: list[str] = []
        self.closed = False

    def exchange(self, tx: str) -> str:
        self.writes.append(tx)
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return "1"

    def close(self) -> None:
        self.closed = True


class CliTests(unittest.TestCase):
    def test_parse_args_defaults(self) -> None:
        args = cli.parse_args(["on", "--port", "COM3"])
        self.assertEqual(args.command, "on")
        self.assertEqual(args.port, "COM3")
        self.assertEqual(args.baud, cli.DEFAULT_BAUD)
        self.assertEqual(args.wait, cli.DEFAULT_WAIT_SECONDS)
        self.assertTrue(args.dry_run)

    def test_parse_args_rejects_legacy_cycle(self) -> None:
        with self.assertRaises(cli.PowerCtlError) as captured:
            cli.parse_args(["cycle", "--port", "COM3"])
        self.assertEqual(captured.exception.exit_code, cli.EXIT_USAGE)
        self.assertEqual(captured.exception.error_code, "invalid_arguments")

    def test_parse_args_rejects_non_finite_float_options(self) -> None:
        cases = (
            ("--wait", "nan"),
            ("--wait", "inf"),
            ("--wait", "-inf"),
            ("--timeout", "nan"),
            ("--timeout", "inf"),
            ("--min-cycle-interval", "nan"),
            ("--min-cycle-interval", "inf"),
        )
        for option, value in cases:
            with self.subTest(option=option, value=value):
                with self.assertRaises(cli.PowerCtlError) as captured:
                    cli.parse_args(
                        [
                            "power-cycle",
                            "--port",
                            "COM3",
                            f"{option}={value}",
                        ]
                    )
                self.assertEqual(captured.exception.exit_code, cli.EXIT_USAGE)
                self.assertEqual(
                    captured.exception.error_code,
                    "invalid_arguments",
                )

    def test_parse_args_rejects_disabled_cycle_rate_limit(self) -> None:
        with self.assertRaises(cli.PowerCtlError) as captured:
            cli.parse_args(
                [
                    "power-cycle",
                    "--port",
                    "COM3",
                    "--min-cycle-interval",
                    "0",
                ]
            )
        self.assertEqual(captured.exception.exit_code, cli.EXIT_USAGE)
        self.assertEqual(captured.exception.error_code, "invalid_arguments")

    def test_parse_args_rejects_abbreviated_safety_flags(self) -> None:
        cases = ("--e", "--exec", "--y", "--js")
        for option in cases:
            with self.subTest(option=option):
                with self.assertRaises(cli.PowerCtlError) as captured:
                    cli.parse_args(
                        [
                            "on",
                            "--port",
                            "COM3",
                            option,
                        ]
                    )
                self.assertEqual(captured.exception.exit_code, cli.EXIT_USAGE)
                self.assertEqual(
                    captured.exception.error_code,
                    "invalid_arguments",
                )

    def test_resolve_port_escapes_control_characters_in_candidates(self) -> None:
        candidate = cli.CandidatePort(
            device="COM9\x1b]0;owned\x07",
            description="USB serial\nforged",
        )
        output: list[str] = []

        with mock.patch.object(cli.sys.stdin, "isatty", return_value=True):
            selected = cli.resolve_port(
                explicit_port=None,
                detect_ports_fn=lambda: [candidate],
                input_fn=lambda _: "1",
                output_fn=output.append,
            )

        rendered = "\n".join(output)
        self.assertEqual(selected, candidate.device)
        self.assertIn("\\u001b]0;owned\\u0007", rendered)
        self.assertIn("USB serial\\nforged", rendered)
        self.assertNotIn("\x1b", rendered)
        self.assertNotIn("\nforged", rendered.replace("\\nforged", ""))

    def test_print_ports_escapes_control_characters_in_text_output(self) -> None:
        candidate = cli.CandidatePort(
            device="COM9\x1b]0;owned\x07",
            description="USB serial\nforged",
        )
        output: list[str] = []

        args = cli.parse_args(["--list-ports"])
        args.log_file = Path("list-ports.log")
        with mock.patch.object(
            cli,
            "append_jsonl_log_best_effort",
            return_value=(args.log_file, True),
        ):
            exit_code = cli.print_ports(
                args=args,
                output_fn=output.append,
                detect_ports_fn=lambda: [candidate],
            )

        rendered = "\n".join(output)
        self.assertEqual(exit_code, cli.EXIT_OK)
        self.assertIn("\\u001b]0;owned\\u0007", rendered)
        self.assertIn("USB serial\\nforged", rendered)
        self.assertNotIn("\x1b", rendered)
        self.assertNotIn("\nforged", rendered.replace("\\nforged", ""))
        self.assertIn("audit_logged=True", rendered)

    def test_list_ports_json_records_audit_result(self) -> None:
        candidate = cli.CandidatePort(device="COM9", description="USB serial")
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "list-ports.log"
            code = cli.main(
                ["--list-ports", "--json", "--log-file", str(log_file)],
                output_stream=stdout,
                error_stream=stderr,
                detect_ports_fn=lambda: [candidate],
                now_fn=lambda: FIXED_NOW,
            )
            log_record = json.loads(log_file.read_text(encoding="utf-8"))

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, cli.EXIT_OK)
        self.assertTrue(payload["audit_logged"])
        self.assertEqual(payload["log_file"], str(log_file))
        self.assertTrue(log_record["audit_logged"])
        self.assertEqual(log_record["command"], "list-ports")
        self.assertEqual(stderr.getvalue().strip(), "")

    def test_list_ports_json_reports_audit_failure(self) -> None:
        primary_log = Path("/tmp/list-ports-primary.log")
        fallback_log = Path("/tmp/list-ports-fallback.log")
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch.object(
            cli,
            "append_jsonl_log",
            side_effect=UnicodeError("audit encoding failed"),
        ):
            with mock.patch.object(
                cli,
                "fallback_log_file",
                return_value=fallback_log,
            ):
                code = cli.main(
                    ["--list-ports", "--json", "--log-file", str(primary_log)],
                    output_stream=stdout,
                    error_stream=stderr,
                    detect_ports_fn=lambda: [],
                    now_fn=lambda: FIXED_NOW,
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, cli.EXIT_OK)
        self.assertFalse(payload["audit_logged"])
        self.assertEqual(payload["log_file"], str(primary_log))
        self.assertEqual(stderr.getvalue().strip(), "")

    def test_internal_error_keeps_audit_schema_when_logging_crashes(self) -> None:
        log_file = Path("/tmp/list-ports.log")
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch.object(
            cli,
            "append_jsonl_log_best_effort",
            side_effect=RuntimeError("unexpected audit failure"),
        ):
            code = cli.main(
                ["--list-ports", "--json", "--log-file", str(log_file)],
                output_stream=stdout,
                error_stream=stderr,
                detect_ports_fn=lambda: [],
                now_fn=lambda: FIXED_NOW,
            )

        payload = json.loads(stderr.getvalue())
        self.assertEqual(code, cli.EXIT_INTERNAL)
        self.assertEqual(stdout.getvalue().strip(), "")
        self.assertFalse(payload["audit_logged"])
        self.assertEqual(payload["log_file"], str(log_file))
        self.assertEqual(payload["error"]["code"], "internal_error")

    def test_confirmation_prompt_escapes_control_characters(self) -> None:
        prompts: list[str] = []

        with mock.patch.object(cli.sys.stdin, "isatty", return_value=True):
            cli.confirm_execute(
                command="on",
                port="COM9\x1b]0;owned\x07\nforged",
                state_before="off",
                input_fn=lambda prompt: prompts.append(prompt) or "yes",
            )

        self.assertEqual(len(prompts), 1)
        self.assertIn("\\u001b]0;owned\\u0007\\nforged", prompts[0])
        self.assertNotIn("\x1b", prompts[0])
        self.assertNotIn("\nforged", prompts[0].replace("\\nforged", ""))

    def test_main_json_input_error_uses_public_error_contract(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "input-error.log"
            code = cli.main(
                [
                    "power-cycle",
                    "--wait=nan",
                    "--json",
                    "--log-file",
                    str(log_file),
                ],
                output_stream=stdout,
                error_stream=stderr,
                now_fn=lambda: FIXED_NOW,
            )

            log_record = json.loads(log_file.read_text(encoding="utf-8"))

        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertEqual(stdout.getvalue().strip(), "")
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["exit_code"], cli.EXIT_USAGE)
        self.assertEqual(payload["error"]["code"], "invalid_arguments")
        self.assertEqual(payload["command"], "unknown")
        self.assertEqual(payload["actions"], [])
        self.assertEqual(payload["log_file"], str(log_file))
        self.assertEqual(log_record["error"]["code"], "invalid_arguments")

    def test_input_error_does_not_log_raw_invalid_value(self) -> None:
        raw_value = "do-not-log-this-value"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "input-error.log"
            code = cli.main(
                [
                    "on",
                    "--baud",
                    raw_value,
                    "--json",
                    "--log-file",
                    str(log_file),
                ],
                output_stream=stdout,
                error_stream=stderr,
                now_fn=lambda: FIXED_NOW,
            )
            logged = log_file.read_text(encoding="utf-8")

        self.assertEqual(code, cli.EXIT_USAGE)
        self.assertNotIn(raw_value, stderr.getvalue())
        self.assertNotIn(raw_value, logged)

    def test_dry_run_does_not_open_transport(self) -> None:
        called = {"value": False}

        def failing_factory(**_: object) -> FakeTransport:
            called["value"] = True
            raise AssertionError("transport factory must not be called in dry-run")

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "powerctl.log"
            code = cli.main(
                [
                    "on",
                    "--port",
                    "COM9",
                    "--json",
                    "--log-file",
                    str(log_file),
                ],
                output_stream=stdout,
                error_stream=stderr,
                transport_factory=failing_factory,
                now_fn=lambda: FIXED_NOW,
            )

        self.assertEqual(code, cli.EXIT_OK)
        self.assertFalse(called["value"])
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["actions"][0]["tx"], "1")
        self.assertEqual(stderr.getvalue().strip(), "")

    def test_json_schema_for_status(self) -> None:
        fake_transport = FakeTransport(["1"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "powerctl.log"
            code = cli.main(
                [
                    "status",
                    "--port",
                    "/dev/ttyUSB0",
                    "--json",
                    "--log-file",
                    str(log_file),
                ],
                output_stream=stdout,
                error_stream=stderr,
                transport_factory=fake_factory,
                now_fn=lambda: FIXED_NOW,
            )

        self.assertEqual(code, cli.EXIT_OK)
        payload = json.loads(stdout.getvalue())
        required_keys = {
            "schema_version",
            "ok",
            "exit_code",
            "command",
            "dry_run",
            "read_only",
            "port",
            "baud",
            "wait_seconds",
            "requested_at",
            "state_before",
            "state_after",
            "actions",
            "log_file",
            "audit_logged",
            "error",
        }
        self.assertTrue(required_keys.issubset(payload.keys()))
        self.assertEqual(payload["command"], "status")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["state_before"], "on")
        self.assertEqual(payload["state_after"], "on")
        self.assertTrue(payload["audit_logged"])
        self.assertIn("read-only status query", payload["note"])
        self.assertEqual(fake_transport.writes, ["s"])
        self.assertEqual(stderr.getvalue().strip(), "")

    def test_parse_state_rejects_trailing_content(self) -> None:
        for response in ("1garbage", "0 ACK", "10"):
            with self.subTest(response=response):
                with self.assertRaises(cli.PowerCtlError) as captured:
                    cli.parse_state(response)
                self.assertEqual(
                    captured.exception.error_code,
                    "unexpected_state",
                )

    def test_text_formatter_reports_read_only_note_and_actions(self) -> None:
        result = cli.CommandResult(
            command="status",
            dry_run=True,
            port="COM9",
            baud=cli.DEFAULT_BAUD,
            wait_seconds=cli.DEFAULT_WAIT_SECONDS,
            requested_at=FIXED_NOW,
            state_before="on",
            state_after="on",
            actions=[
                cli.ActionEntry(
                    step="status",
                    tx="s",
                    rx="\x1b]0;owned\x07\nforged",
                )
            ],
            note="read-only status query",
        )
        payload = result.to_payload(
            ok=True,
            exit_code=cli.EXIT_OK,
            log_file=Path("powerctl.log"),
            error=None,
        )

        output = cli.format_text_result(payload)

        self.assertIn("read_only=True", output)
        self.assertIn("audit_logged=None", output)
        self.assertIn('note="read-only status query"', output)
        self.assertIn('action step="status" tx="s"', output)
        self.assertIn("\\u001b]0;owned\\u0007\\nforged", output)
        self.assertNotIn("\x1b", output)
        self.assertNotIn("\nforged", output.replace("\\nforged", ""))

    def test_execute_on_reads_status_before_write(self) -> None:
        fake_transport = FakeTransport(["0", "ACK", "1"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "powerctl.log"
            code = cli.main(
                [
                    "on",
                    "--port",
                    "COM9",
                    "--execute",
                    "--yes",
                    "--json",
                    "--log-file",
                    str(log_file),
                ],
                output_stream=stdout,
                error_stream=stderr,
                transport_factory=fake_factory,
                now_fn=lambda: FIXED_NOW,
            )

        self.assertEqual(code, cli.EXIT_OK)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["dry_run"])
        self.assertEqual(payload["state_before"], "off")
        self.assertEqual(payload["state_after"], "on")
        self.assertEqual(fake_transport.writes, ["s", "1", "s"])
        self.assertEqual(stderr.getvalue().strip(), "")

    def test_execute_on_fails_when_verified_state_is_off(self) -> None:
        fake_transport = FakeTransport(["0", "ACK", "0"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "powerctl.log"
            code = cli.main(
                [
                    "on",
                    "--port",
                    "COM9",
                    "--execute",
                    "--yes",
                    "--json",
                    "--log-file",
                    str(log_file),
                ],
                output_stream=stdout,
                error_stream=stderr,
                transport_factory=fake_factory,
                now_fn=lambda: FIXED_NOW,
            )

        self.assertEqual(code, cli.EXIT_PROTOCOL)
        self.assertEqual(stdout.getvalue().strip(), "")
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "state_verification_failed")
        self.assertEqual(payload["state_before"], "off")
        self.assertEqual(payload["state_after"], "off")
        self.assertEqual(
            [action["step"] for action in payload["actions"]],
            ["status_before", "on", "status_after"],
        )
        self.assertEqual(fake_transport.writes, ["s", "1", "s"])

    def test_execute_without_yes_aborts_when_non_interactive(self) -> None:
        fake_transport = FakeTransport(["1"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "powerctl.log"
            fake_stdin = mock.Mock()
            fake_stdin.isatty.return_value = False
            with mock.patch("usb_power_switch_ctl.cli.sys.stdin", fake_stdin):
                code = cli.main(
                    [
                        "off",
                        "--port",
                        "COM9",
                        "--execute",
                        "--json",
                        "--log-file",
                        str(log_file),
                    ],
                    output_stream=stdout,
                    error_stream=stderr,
                    transport_factory=fake_factory,
                    now_fn=lambda: FIXED_NOW,
                )

        self.assertEqual(code, cli.EXIT_ABORTED)
        self.assertEqual(stdout.getvalue().strip(), "")
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "confirmation_required")
        self.assertEqual(fake_transport.writes, ["s"])

    def test_cycle_rate_limit_blocks_writes_after_status_check(self) -> None:
        fake_transport = FakeTransport(["1"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "powerctl.log"
            stamp_file = Path(tmp) / "last_cycle_epoch.txt"
            stamp_file.parent.mkdir(parents=True, exist_ok=True)
            stamp_file.write_text("999.000000", encoding="utf-8")
            with mock.patch(
                "usb_power_switch_ctl.cli.cycle_stamp_path",
                return_value=stamp_file,
            ):
                with mock.patch("usb_power_switch_ctl.cli.time.time", return_value=1000.0):
                    code = cli.main(
                        [
                            "power-cycle",
                            "--port",
                            "COM9",
                            "--execute",
                            "--yes",
                            "--wait",
                            "0",
                            "--min-cycle-interval",
                            "5",
                            "--json",
                            "--log-file",
                            str(log_file),
                        ],
                        output_stream=stdout,
                        error_stream=stderr,
                        transport_factory=fake_factory,
                        now_fn=lambda: FIXED_NOW,
                    )

        self.assertEqual(code, cli.EXIT_RATE_LIMIT)
        self.assertEqual(stdout.getvalue().strip(), "")
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "cycle_rate_limited")
        self.assertEqual(fake_transport.writes, ["s"])

    def test_cycle_stamp_write_failure_blocks_power_side_effects(self) -> None:
        fake_transport = FakeTransport(["1"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "powerctl.log"
            stamp_file = Path(tmp) / "state" / "last_cycle_epoch.txt"
            with mock.patch(
                "usb_power_switch_ctl.cli.cycle_stamp_path",
                return_value=stamp_file,
            ):
                with mock.patch(
                    "usb_power_switch_ctl.cli.write_cycle_stamp",
                    side_effect=PermissionError("state path is read-only"),
                ):
                    with mock.patch(
                        "usb_power_switch_ctl.cli.time.time",
                        return_value=1000.0,
                    ):
                        code = cli.main(
                            [
                                "power-cycle",
                                "--port",
                                "COM9",
                                "--execute",
                                "--yes",
                                "--wait",
                                "0",
                                "--json",
                                "--log-file",
                                str(log_file),
                            ],
                            output_stream=stdout,
                            error_stream=stderr,
                            transport_factory=fake_factory,
                            now_fn=lambda: FIXED_NOW,
                        )

        self.assertEqual(code, cli.EXIT_INTERNAL)
        self.assertEqual(stdout.getvalue().strip(), "")
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "internal_error")
        self.assertEqual(fake_transport.writes, ["s"])
        self.assertTrue(fake_transport.closed)

    def test_cycle_corrupt_stamp_blocks_power_side_effects(self) -> None:
        fake_transport = FakeTransport(["1"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "powerctl.log"
            stamp_file = Path(tmp) / "state" / "last_cycle_epoch.txt"
            stamp_file.parent.mkdir(parents=True)
            stamp_file.write_text("not-a-number", encoding="utf-8")
            with mock.patch(
                "usb_power_switch_ctl.cli.cycle_stamp_path",
                return_value=stamp_file,
            ):
                with mock.patch(
                    "usb_power_switch_ctl.cli.time.time",
                    return_value=1000.0,
                ):
                    code = cli.main(
                        [
                            "power-cycle",
                            "--port",
                            "COM9",
                            "--execute",
                            "--yes",
                            "--wait",
                            "0",
                            "--json",
                            "--log-file",
                            str(log_file),
                        ],
                        output_stream=stdout,
                        error_stream=stderr,
                        transport_factory=fake_factory,
                        now_fn=lambda: FIXED_NOW,
                    )

        self.assertEqual(code, cli.EXIT_INTERNAL)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["error"]["code"], "cycle_state_invalid")
        self.assertEqual(payload["state_before"], "on")
        self.assertEqual(
            [action["step"] for action in payload["actions"]],
            ["status_before"],
        )
        self.assertEqual(fake_transport.writes, ["s"])

    def test_cycle_existing_reservation_blocks_power_side_effects(self) -> None:
        fake_transport = FakeTransport(["1"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "powerctl.log"
            stamp_file = Path(tmp) / "state" / "last_cycle_epoch.txt"
            lock_file = cli.cycle_lock_path(stamp_file)
            with mock.patch(
                "usb_power_switch_ctl.cli.cycle_stamp_path",
                return_value=stamp_file,
            ):
                with mock.patch(
                    "usb_power_switch_ctl.cli.time.time",
                    return_value=1000.0,
                ):
                    with cli.cycle_rate_lock(lock_file):
                        code = cli.main(
                            [
                                "power-cycle",
                                "--port",
                                "COM9",
                                "--execute",
                                "--yes",
                                "--wait",
                                "0",
                                "--json",
                                "--log-file",
                                str(log_file),
                            ],
                            output_stream=stdout,
                            error_stream=stderr,
                            transport_factory=fake_factory,
                            now_fn=lambda: FIXED_NOW,
                        )

        self.assertEqual(code, cli.EXIT_RATE_LIMIT)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["error"]["code"], "cycle_reservation_busy")
        self.assertEqual(payload["state_before"], "on")
        self.assertEqual(fake_transport.writes, ["s"])

    def test_cycle_partial_failure_reports_attempted_actions(self) -> None:
        fake_transport = FakeTransport(
            [
                "1",
                "ACK",
                "0",
                cli.PowerCtlError(
                    "simulated ON timeout",
                    cli.EXIT_PROTOCOL,
                    "device_timeout",
                ),
                "ACK",
                "1",
            ]
        )

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "powerctl.log"
            stamp_file = Path(tmp) / "state" / "last_cycle_epoch.txt"
            with mock.patch(
                "usb_power_switch_ctl.cli.cycle_stamp_path",
                return_value=stamp_file,
            ):
                with mock.patch(
                    "usb_power_switch_ctl.cli.time.time",
                    return_value=1000.0,
                ):
                    code = cli.main(
                        [
                            "power-cycle",
                            "--port",
                            "COM9",
                            "--execute",
                            "--yes",
                            "--wait",
                            "0",
                            "--json",
                            "--log-file",
                            str(log_file),
                        ],
                        output_stream=stdout,
                        error_stream=stderr,
                        transport_factory=fake_factory,
                        now_fn=lambda: FIXED_NOW,
                    )

        self.assertEqual(code, cli.EXIT_PROTOCOL)
        self.assertEqual(stdout.getvalue().strip(), "")
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["error"]["code"], "device_timeout")
        self.assertEqual(payload["state_before"], "on")
        self.assertEqual(payload["state_after"], "on")
        self.assertIn("recovery ON verified", payload["note"])
        self.assertEqual(
            [action["step"] for action in payload["actions"]],
            [
                "status_before",
                "cycle_off",
                "status_cycle_off",
                "cycle_wait",
                "cycle_on",
                "cycle_recovery_on",
                "status_after_recovery",
            ],
        )
        self.assertEqual(payload["actions"][4]["tx"], "1")
        self.assertIsNone(payload["actions"][4]["rx"])
        self.assertEqual(payload["actions"][4]["note"], "attempted; no response")
        self.assertEqual(fake_transport.writes, ["s", "0", "s", "1", "1", "s"])

    def test_cycle_recovery_failure_preserves_original_error(self) -> None:
        fake_transport = FakeTransport(
            [
                "1",
                "ACK",
                "0",
                cli.PowerCtlError(
                    "simulated ON timeout",
                    cli.EXIT_PROTOCOL,
                    "device_timeout",
                ),
                cli.PowerCtlError(
                    "simulated recovery failure",
                    cli.EXIT_PROTOCOL,
                    "serial_io_failed",
                ),
            ]
        )

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "powerctl.log"
            stamp_file = Path(tmp) / "state" / "last_cycle_epoch.txt"
            with mock.patch(
                "usb_power_switch_ctl.cli.cycle_stamp_path",
                return_value=stamp_file,
            ):
                with mock.patch(
                    "usb_power_switch_ctl.cli.time.time",
                    return_value=1000.0,
                ):
                    code = cli.main(
                        [
                            "power-cycle",
                            "--port",
                            "COM9",
                            "--execute",
                            "--yes",
                            "--wait",
                            "0",
                            "--json",
                            "--log-file",
                            str(log_file),
                        ],
                        output_stream=stdout,
                        error_stream=stderr,
                        transport_factory=fake_factory,
                        now_fn=lambda: FIXED_NOW,
                    )

        self.assertEqual(code, cli.EXIT_PROTOCOL)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["error"]["code"], "device_timeout")
        self.assertEqual(payload["state_before"], "on")
        self.assertEqual(payload["state_after"], "off")
        self.assertIn("recovery ON not verified", payload["note"])
        self.assertEqual(
            [action["step"] for action in payload["actions"]],
            [
                "status_before",
                "cycle_off",
                "status_cycle_off",
                "cycle_wait",
                "cycle_on",
                "cycle_recovery_on",
            ],
        )
        self.assertEqual(payload["actions"][-1]["tx"], "1")
        self.assertIsNone(payload["actions"][-1]["rx"])
        self.assertEqual(payload["actions"][-1]["note"], "attempted; no response")
        self.assertEqual(fake_transport.writes, ["s", "0", "s", "1", "1"])

    def test_cycle_holds_reservation_through_state_verification(self) -> None:
        fake_transport = FakeTransport(["1", "ACK", "0", "ACK", "1"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        lock_errors: list[str] = []
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "powerctl.log"
            stamp_file = Path(tmp) / "state" / "last_cycle_epoch.txt"

            def probe_lock(_: float) -> None:
                try:
                    with cli.cycle_rate_lock(cli.cycle_lock_path(stamp_file)):
                        self.fail("concurrent cycle lock must not be acquired")
                except cli.PowerCtlError as exc:
                    lock_errors.append(exc.error_code)

            with mock.patch(
                "usb_power_switch_ctl.cli.cycle_stamp_path",
                return_value=stamp_file,
            ):
                with mock.patch(
                    "usb_power_switch_ctl.cli.time.time",
                    return_value=1000.0,
                ):
                    with mock.patch(
                        "usb_power_switch_ctl.cli.time.sleep",
                        side_effect=probe_lock,
                    ):
                        code = cli.main(
                            [
                                "power-cycle",
                                "--port",
                                "COM9",
                                "--execute",
                                "--yes",
                                "--wait",
                                "10",
                                "--min-cycle-interval",
                                "5",
                                "--json",
                                "--log-file",
                                str(log_file),
                            ],
                            output_stream=stdout,
                            error_stream=stderr,
                            transport_factory=fake_factory,
                            now_fn=lambda: FIXED_NOW,
                        )

        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(lock_errors, ["cycle_reservation_busy"])
        self.assertEqual(fake_transport.writes, ["s", "0", "s", "1", "s"])

    def test_cycle_interrupt_recovers_on_and_reports_context(self) -> None:
        fake_transport = FakeTransport(["1", "ACK", "0", "ACK", "1"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "powerctl.log"
            stamp_file = Path(tmp) / "state" / "last_cycle_epoch.txt"
            with mock.patch(
                "usb_power_switch_ctl.cli.cycle_stamp_path",
                return_value=stamp_file,
            ):
                with mock.patch(
                    "usb_power_switch_ctl.cli.time.time",
                    return_value=1000.0,
                ):
                    with mock.patch(
                        "usb_power_switch_ctl.cli.time.sleep",
                        side_effect=KeyboardInterrupt,
                    ):
                        code = cli.main(
                            [
                                "power-cycle",
                                "--port",
                                "COM9",
                                "--execute",
                                "--yes",
                                "--wait",
                                "3",
                                "--json",
                                "--log-file",
                                str(log_file),
                            ],
                            output_stream=stdout,
                            error_stream=stderr,
                            transport_factory=fake_factory,
                            now_fn=lambda: FIXED_NOW,
                        )

        self.assertEqual(code, cli.EXIT_ABORTED)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["error"]["code"], "cycle_interrupted")
        self.assertEqual(payload["state_before"], "on")
        self.assertEqual(payload["state_after"], "on")
        self.assertIn("recovery ON verified", payload["note"])
        self.assertEqual(
            [action["step"] for action in payload["actions"]],
            [
                "status_before",
                "cycle_off",
                "status_cycle_off",
                "cycle_wait",
                "cycle_recovery_on",
                "status_after_recovery",
            ],
        )
        self.assertEqual(fake_transport.writes, ["s", "0", "s", "1", "s"])

    def test_cycle_aborts_when_off_state_is_not_verified(self) -> None:
        fake_transport = FakeTransport(["1", "ACK", "1", "ACK", "1"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "powerctl.log"
            stamp_file = Path(tmp) / "state" / "last_cycle_epoch.txt"
            with mock.patch(
                "usb_power_switch_ctl.cli.cycle_stamp_path",
                return_value=stamp_file,
            ):
                with mock.patch(
                    "usb_power_switch_ctl.cli.time.time",
                    return_value=1000.0,
                ):
                    code = cli.main(
                        [
                            "power-cycle",
                            "--port",
                            "COM9",
                            "--execute",
                            "--yes",
                            "--wait",
                            "0",
                            "--json",
                            "--log-file",
                            str(log_file),
                        ],
                        output_stream=stdout,
                        error_stream=stderr,
                        transport_factory=fake_factory,
                        now_fn=lambda: FIXED_NOW,
                    )

        self.assertEqual(code, cli.EXIT_PROTOCOL)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(
            payload["error"]["code"],
            "cycle_off_verification_failed",
        )
        self.assertEqual(payload["state_after"], "on")
        self.assertNotIn(
            "cycle_wait",
            [action["step"] for action in payload["actions"]],
        )
        self.assertIn("recovery ON verified", payload["note"])
        self.assertEqual(fake_transport.writes, ["s", "0", "s", "1", "s"])

    def test_cycle_rate_limit_survives_log_path_switch(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            fallback_log = Path(tmp) / "fallback-powerctl.log"
            primary_log = Path(tmp) / "primary-powerctl.log"
            stamp_file = Path(tmp) / "state" / "last_cycle_epoch.txt"
            transports = [
                FakeTransport(["1", "ACK", "0", "ACK", "1"]),
                FakeTransport(["1"]),
            ]
            stamp_files: list[Path] = []

            def fake_factory(**_: object) -> FakeTransport:
                return transports.pop(0)

            with mock.patch(
                "usb_power_switch_ctl.cli.cycle_stamp_path",
                return_value=stamp_file,
            ):
                with mock.patch(
                    "usb_power_switch_ctl.cli.time.time",
                    side_effect=[1000.0, 1001.0],
                ):
                    first_code = cli.main(
                        [
                            "power-cycle",
                            "--port",
                            "COM9",
                            "--execute",
                            "--yes",
                            "--wait",
                            "0",
                            "--min-cycle-interval",
                            "5",
                            "--json",
                            "--log-file",
                            str(fallback_log),
                        ],
                        output_stream=stdout,
                        error_stream=stderr,
                        transport_factory=fake_factory,
                        now_fn=lambda: FIXED_NOW,
                    )
                    second_code = cli.main(
                        [
                            "power-cycle",
                            "--port",
                            "COM9",
                            "--execute",
                            "--yes",
                            "--wait",
                            "0",
                            "--min-cycle-interval",
                            "5",
                            "--json",
                            "--log-file",
                            str(primary_log),
                        ],
                        output_stream=stdout,
                        error_stream=stderr,
                        transport_factory=fake_factory,
                        now_fn=lambda: FIXED_NOW,
                    )
                stamp_files = list(stamp_file.parent.rglob("last_cycle_epoch.txt"))

        self.assertEqual(first_code, cli.EXIT_OK)
        self.assertEqual(second_code, cli.EXIT_RATE_LIMIT)
        self.assertEqual(transports, [])
        self.assertEqual(len(stamp_files), 1)

    def test_cycle_stamp_path_uses_standard_state_environment(self) -> None:
        cases = (
            (
                "nt",
                "win32",
                "LOCALAPPDATA",
                r"C:\redirected-state",
                PureWindowsPath,
            ),
            (
                "posix",
                "linux",
                "XDG_STATE_HOME",
                "/redirected-state",
                PurePosixPath,
            ),
        )
        for os_name, platform, env_var, root, path_class in cases:
            with self.subTest(platform=platform):
                with mock.patch.object(cli.os, "name", os_name):
                    with mock.patch.object(cli.sys, "platform", platform):
                        with mock.patch.object(cli, "Path", path_class):
                            with mock.patch.dict(
                                os.environ,
                                {env_var: root},
                                clear=False,
                            ):
                                stamp_file = cli.cycle_stamp_path()

                self.assertEqual(
                    stamp_file,
                    path_class(root) / cli.APP_NAME / "last_cycle_epoch.txt",
                )

    def test_fallback_log_file_uses_private_temp_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(cli, "_fallback_log_dir", None):
                with mock.patch.object(cli.tempfile, "gettempdir", return_value=tmp):
                    fallback_log = cli.fallback_log_file()

            self.assertEqual(fallback_log.parent.parent, Path(tmp))
            self.assertTrue(fallback_log.parent.name.startswith(f"{cli.APP_NAME}-"))
            mode = stat.S_IMODE(fallback_log.parent.stat().st_mode)
            if os.name != "nt":
                self.assertEqual(mode & 0o077, 0)

    def test_log_file_falls_back_when_primary_write_fails(self) -> None:
        primary_log = Path("/tmp/primary-powerctl.log")
        fallback_log = Path("/tmp/fallback-powerctl.log")
        fake_transport = FakeTransport(["1"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        def fake_append(log_file: Path, payload: dict[str, object]) -> None:
            if log_file == primary_log:
                raise PermissionError("primary denied")

        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch("usb_power_switch_ctl.cli.append_jsonl_log", side_effect=fake_append):
            with mock.patch("usb_power_switch_ctl.cli.fallback_log_file", return_value=fallback_log):
                code = cli.main(
                    [
                        "status",
                        "--port",
                        "COM9",
                        "--json",
                        "--log-file",
                        str(primary_log),
                    ],
                    output_stream=stdout,
                    error_stream=stderr,
                    transport_factory=fake_factory,
                    now_fn=lambda: FIXED_NOW,
                )

        self.assertEqual(code, cli.EXIT_OK)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["log_file"], str(fallback_log))
        self.assertTrue(payload["audit_logged"])
        self.assertEqual(stderr.getvalue().strip(), "")

    def test_special_file_log_path_falls_back_to_regular_file(self) -> None:
        special_log = Path("NUL") if os.name == "nt" else Path("/dev/null")
        fake_transport = FakeTransport(["1"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            fallback_log = Path(tmp) / "fallback-powerctl.log"
            with mock.patch.object(
                cli,
                "fallback_log_file",
                return_value=fallback_log,
            ):
                code = cli.main(
                    [
                        "status",
                        "--port",
                        "COM9",
                        "--json",
                        "--log-file",
                        str(special_log),
                    ],
                    output_stream=stdout,
                    error_stream=stderr,
                    transport_factory=fake_factory,
                    now_fn=lambda: FIXED_NOW,
                )
            log_record = json.loads(fallback_log.read_text(encoding="utf-8"))

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(payload["log_file"], str(fallback_log))
        self.assertTrue(payload["audit_logged"])
        self.assertTrue(log_record["audit_logged"])
        self.assertEqual(stderr.getvalue().strip(), "")

    def test_result_reports_when_primary_and_fallback_logs_fail(self) -> None:
        primary_log = Path("/tmp/primary-powerctl.log")
        fallback_log = Path("/tmp/fallback-powerctl.log")
        fake_transport = FakeTransport(["1"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch(
            "usb_power_switch_ctl.cli.append_jsonl_log",
            side_effect=PermissionError("audit denied"),
        ):
            with mock.patch(
                "usb_power_switch_ctl.cli.fallback_log_file",
                return_value=fallback_log,
            ):
                code = cli.main(
                    [
                        "status",
                        "--port",
                        "COM9",
                        "--json",
                        "--log-file",
                        str(primary_log),
                    ],
                    output_stream=stdout,
                    error_stream=stderr,
                    transport_factory=fake_factory,
                    now_fn=lambda: FIXED_NOW,
                )

        self.assertEqual(code, cli.EXIT_OK)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["log_file"], str(primary_log))
        self.assertFalse(payload["audit_logged"])
        self.assertEqual(stderr.getvalue().strip(), "")

    def test_text_output_reports_fallback_log_file(self) -> None:
        fake_transport = FakeTransport(["1"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        with tempfile.TemporaryDirectory() as tmp:
            primary_log = Path(tmp) / "primary-powerctl.log"
            fallback_log = Path(tmp) / "fallback-powerctl.log"

            def fake_append(log_file: Path, payload: dict[str, object]) -> None:
                if log_file == primary_log:
                    raise PermissionError("primary denied")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch(
                "usb_power_switch_ctl.cli.append_jsonl_log",
                side_effect=fake_append,
            ):
                with mock.patch(
                    "usb_power_switch_ctl.cli.fallback_log_file",
                    return_value=fallback_log,
                ):
                    code = cli.main(
                        [
                            "status",
                            "--port",
                            "COM9",
                            "--log-file",
                            str(primary_log),
                        ],
                        output_stream=stdout,
                        error_stream=stderr,
                        transport_factory=fake_factory,
                        now_fn=lambda: FIXED_NOW,
                    )

        self.assertEqual(code, cli.EXIT_OK)
        expected_log_line = "log_file={log_file} audit_logged=True".format(
            log_file=json.dumps(str(fallback_log), ensure_ascii=True),
        )
        self.assertIn(expected_log_line, stdout.getvalue().splitlines())
        self.assertEqual(stderr.getvalue().strip(), "")

    def test_log_file_can_be_set_by_environment_variable(self) -> None:
        fake_transport = FakeTransport(["0"])

        def fake_factory(**_: object) -> FakeTransport:
            return fake_transport

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            env_log_file = str(Path(tmp) / "env-powerctl.log")
            with mock.patch.dict(os.environ, {cli.LOG_FILE_ENV_VAR: env_log_file}, clear=False):
                code = cli.main(
                    [
                        "status",
                        "--port",
                        "COM9",
                        "--json",
                    ],
                    output_stream=stdout,
                    error_stream=stderr,
                    transport_factory=fake_factory,
                    now_fn=lambda: FIXED_NOW,
                )

        self.assertEqual(code, cli.EXIT_OK)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["log_file"], env_log_file)
        self.assertEqual(stderr.getvalue().strip(), "")


if __name__ == "__main__":
    unittest.main()
