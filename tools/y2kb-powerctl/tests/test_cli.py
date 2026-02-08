import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from y2kb_powerctl import cli


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


if __name__ == "__main__":
    unittest.main()
