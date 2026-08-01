import io
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from usb_power_switch_ctl import cli


FIXED_NOW = datetime(2026, 2, 8, 0, 0, tzinfo=timezone.utc)


class FakeTransport:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.writes: list[str] = []
        self.closed = False

    def exchange(self, tx: str) -> str:
        self.writes.append(tx)
        if self.responses:
            return self.responses.pop(0)
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
        with self.assertRaises(SystemExit):
            cli.parse_args(["cycle", "--port", "COM3"])

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
            "port",
            "baud",
            "wait_seconds",
            "requested_at",
            "state_before",
            "state_after",
            "actions",
            "log_file",
            "error",
        }
        self.assertTrue(required_keys.issubset(payload.keys()))
        self.assertEqual(payload["command"], "status")
        self.assertEqual(payload["state_before"], "on")
        self.assertEqual(payload["state_after"], "on")
        self.assertEqual(fake_transport.writes, ["s"])
        self.assertEqual(stderr.getvalue().strip(), "")

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

    def test_cycle_rate_limit_survives_log_path_switch(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            fallback_log = Path(tmp) / "fallback-powerctl.log"
            primary_log = Path(tmp) / "primary-powerctl.log"
            home_root = Path(tmp) / "home"
            transports = [
                FakeTransport(["1", "ACK", "ACK", "1"]),
                FakeTransport(["1"]),
            ]
            stamp_files: list[Path] = []

            def fake_factory(**_: object) -> FakeTransport:
                return transports.pop(0)

            with mock.patch("usb_power_switch_ctl.cli.Path.home", return_value=home_root):
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
                stamp_files = list(home_root.rglob("last_cycle_epoch.txt"))

        self.assertEqual(first_code, cli.EXIT_OK)
        self.assertEqual(second_code, cli.EXIT_RATE_LIMIT)
        self.assertEqual(transports, [])
        self.assertEqual(len(stamp_files), 1)

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
