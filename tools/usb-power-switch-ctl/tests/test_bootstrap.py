from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP_PATH = REPOSITORY_ROOT / "scripts" / "bootstrap.py"
SPEC = importlib.util.spec_from_file_location("usb_power_switch_bootstrap", BOOTSTRAP_PATH)
assert SPEC is not None
assert SPEC.loader is not None
bootstrap_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bootstrap_module
SPEC.loader.exec_module(bootstrap_module)


class BootstrapTests(unittest.TestCase):
    def make_minimal_skill_source(self, parent: Path) -> Path:
        source = parent / "source"
        source.mkdir()
        for name in bootstrap_module.COPY_ROOT_FILES:
            (source / name).write_text(name, encoding="utf-8")
        for name in bootstrap_module.COPY_ROOT_DIRECTORIES:
            (source / name).mkdir()
        return source

    def test_parse_args_uses_default_venv(self) -> None:
        args = bootstrap_module.parse_args([])

        self.assertEqual(args.venv_dir, bootstrap_module.DEFAULT_VENV_DIR)
        self.assertEqual(args.venv_dir.name, bootstrap_module.DEFAULT_VENV_NAME)
        self.assertIsNone(args.install_to)

    def test_platform_venv_name_separates_supported_operating_systems(self) -> None:
        self.assertEqual(bootstrap_module.platform_venv_name("win32"), ".venv-windows")
        self.assertEqual(bootstrap_module.platform_venv_name("linux"), ".venv-linux")
        self.assertEqual(bootstrap_module.platform_venv_name("linux2"), ".venv-linux")
        self.assertEqual(bootstrap_module.platform_venv_name("darwin"), ".venv-macos")

    def test_platform_venv_name_rejects_unsupported_platform(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported platform"):
            bootstrap_module.platform_venv_name("freebsd14")

    def test_venv_python_path_uses_platform_layout(self) -> None:
        venv_dir = Path("example-venv")
        with mock.patch.object(bootstrap_module.sys, "platform", "win32"):
            self.assertEqual(
                bootstrap_module.venv_python_path(venv_dir),
                venv_dir / "Scripts" / "python.exe",
            )
        with mock.patch.object(bootstrap_module.sys, "platform", "linux"):
            self.assertEqual(
                bootstrap_module.venv_python_path(venv_dir),
                venv_dir / "bin" / "python",
            )

    def test_parse_probe_output_accepts_successful_list_ports_payload(self) -> None:
        payload = {"ok": True, "command": "list-ports", "ports": [{"device": "COM3"}]}

        self.assertEqual(bootstrap_module.parse_probe_output(json.dumps(payload)), 1)

    def test_parse_probe_output_rejects_non_list_ports_payload(self) -> None:
        with self.assertRaisesRegex(ValueError, "successful list-ports"):
            bootstrap_module.parse_probe_output('{"ok": true, "command": "status"}')

    def test_bootstrap_reuses_venv_and_runs_only_install_and_safe_probe(self) -> None:
        calls: list[tuple[list[str], Path]] = []

        def fake_runner(command: list[str], cwd: Path) -> object:
            calls.append((list(command), cwd))
            if "-c" in command:
                return bootstrap_module.CommandOutcome(0, "[3, 9, 0]", "")
            if "pip" in command:
                return bootstrap_module.CommandOutcome(0, "installed", "")
            return bootstrap_module.CommandOutcome(
                0,
                json.dumps({"ok": True, "command": "list-ports", "ports": []}),
                "",
            )

        with tempfile.TemporaryDirectory() as tmp:
            venv_dir = Path(tmp) / "venv"
            python_path = bootstrap_module.venv_python_path(venv_dir)
            python_path.parent.mkdir(parents=True)
            python_path.touch()
            output = io.StringIO()

            with redirect_stdout(output):
                result = bootstrap_module.bootstrap(venv_dir, run_command=fake_runner)

        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 3)
        self.assertIn("-c", calls[0][0])
        self.assertIn("pip", calls[1][0])
        self.assertEqual(
            calls[2][0][-2:],
            ["--list-ports", "--json"],
        )
        self.assertNotIn("--execute", calls[2][0])
        self.assertIn("No device was selected or modified", output.getvalue())

    def test_bootstrap_refuses_to_overwrite_incomplete_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv_dir = Path(tmp) / "venv"
            venv_dir.mkdir()
            output = io.StringIO()

            with redirect_stdout(output):
                result = bootstrap_module.bootstrap(venv_dir)

        self.assertEqual(result, 1)
        self.assertIn("inspect or remove that directory manually", output.getvalue())

    def test_bootstrap_reports_unstartable_existing_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv_dir = Path(tmp) / "venv"
            python_path = bootstrap_module.venv_python_path(venv_dir)
            python_path.parent.mkdir(parents=True)
            python_path.touch()
            output = io.StringIO()

            with redirect_stdout(output):
                result = bootstrap_module.bootstrap(
                    venv_dir,
                    run_command=mock.Mock(side_effect=OSError("not executable")),
                )

        self.assertEqual(result, 1)
        self.assertIn("Could not start the existing virtual environment Python", output.getvalue())
        self.assertIn(str(venv_dir), output.getvalue())
        self.assertIn("recreate this virtual environment manually", output.getvalue())

    def test_bootstrap_rejects_existing_venv_python_version_check_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv_dir = Path(tmp) / "venv"
            python_path = bootstrap_module.venv_python_path(venv_dir)
            python_path.parent.mkdir(parents=True)
            python_path.touch()
            runner = mock.Mock(
                return_value=bootstrap_module.CommandOutcome(7, "", "runtime failure")
            )
            output = io.StringIO()

            with redirect_stdout(output):
                result = bootstrap_module.bootstrap(venv_dir, run_command=runner)

        self.assertEqual(result, 1)
        runner.assert_called_once()
        self.assertIn("version check failed (exit=7)", output.getvalue())
        self.assertIn("runtime failure", output.getvalue())
        self.assertIn(str(python_path), output.getvalue())
        self.assertIn("recreate this virtual environment manually", output.getvalue())

    def test_bootstrap_rejects_invalid_existing_venv_python_version_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv_dir = Path(tmp) / "venv"
            python_path = bootstrap_module.venv_python_path(venv_dir)
            python_path.parent.mkdir(parents=True)
            python_path.touch()
            runner = mock.Mock(
                return_value=bootstrap_module.CommandOutcome(0, "not-json", "")
            )
            output = io.StringIO()

            with redirect_stdout(output):
                result = bootstrap_module.bootstrap(venv_dir, run_command=runner)

        self.assertEqual(result, 1)
        runner.assert_called_once()
        self.assertIn("invalid Python version", output.getvalue())
        self.assertIn(str(python_path), output.getvalue())
        self.assertIn("recreate this virtual environment manually", output.getvalue())

    def test_bootstrap_rejects_existing_venv_using_python_3_8(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv_dir = Path(tmp) / "venv"
            python_path = bootstrap_module.venv_python_path(venv_dir)
            python_path.parent.mkdir(parents=True)
            python_path.touch()
            runner = mock.Mock(
                return_value=bootstrap_module.CommandOutcome(0, "[3, 8, 19]", "")
            )
            create_venv = mock.Mock()
            output = io.StringIO()

            with redirect_stdout(output):
                result = bootstrap_module.bootstrap(
                    venv_dir,
                    run_command=runner,
                    create_venv=create_venv,
                )

        self.assertEqual(result, 1)
        runner.assert_called_once()
        create_venv.assert_not_called()
        self.assertIn("Python 3.8.19", output.getvalue())
        self.assertIn("Python 3.9+ is required", output.getvalue())
        self.assertIn(str(python_path), output.getvalue())
        self.assertIn("recreate this virtual environment manually", output.getvalue())

    def test_install_skill_copies_only_distributable_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = self.make_minimal_skill_source(parent)
            transient_venvs = (".venv", ".venv-windows", ".venv-linux", ".venv-macos")
            for name in transient_venvs:
                (source / "tools" / name).mkdir()
                (source / "tools" / name / "python").write_text("ignored", encoding="utf-8")
            (source / "scripts" / "bootstrap.py").write_text("script", encoding="utf-8")
            target = parent / "installed-skill"

            result = bootstrap_module.install_skill(target, source_root=source)

            self.assertEqual(result, target)
            self.assertTrue((target / "SKILL.md").is_file())
            self.assertTrue((target / "scripts" / "bootstrap.py").is_file())
            for name in transient_venvs:
                self.assertFalse((target / "tools" / name).exists())
            self.assertFalse((target / "AGENTS.md").exists())

    def test_install_skill_creates_missing_target_parents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = self.make_minimal_skill_source(parent)
            target = parent / "agent" / "skills" / "installed-skill"

            result = bootstrap_module.install_skill(target, source_root=source)

            self.assertEqual(result, target)
            self.assertTrue((target / "SKILL.md").is_file())

    def test_install_skill_rejects_relative_or_existing_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute"):
            bootstrap_module.install_skill(Path("relative-target"))

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            with self.assertRaisesRegex(ValueError, "already exists"):
                bootstrap_module.install_skill(target)

    def test_install_skill_rejects_target_inside_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = self.make_minimal_skill_source(Path(tmp))
            target = source / "nested-install"

            with self.assertRaisesRegex(ValueError, "outside"):
                bootstrap_module.install_skill(target, source_root=source)

    def test_install_skill_does_not_replace_target_created_after_precheck(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = self.make_minimal_skill_source(parent)
            target = parent / "installed-skill"
            target.mkdir()
            marker = target / "preserve-me.txt"
            marker.write_text("existing target", encoding="utf-8")

            with mock.patch.object(bootstrap_module.os.path, "lexists", return_value=False):
                with self.assertRaisesRegex(ValueError, "already exists"):
                    bootstrap_module.install_skill(target, source_root=source)

            self.assertEqual(marker.read_text(encoding="utf-8"), "existing target")

    def test_install_skill_preserves_partial_target_and_concurrent_file_on_copy_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source = self.make_minimal_skill_source(parent)
            target = parent / "installed-skill"
            concurrent_marker = target / "created-concurrently.txt"

            def fail_during_copy(source_path: str, destination_path: str) -> str:
                destination = Path(destination_path)
                if Path(source_path).name == "SKILL.md":
                    destination.write_text("partial copy", encoding="utf-8")
                    return str(destination)
                concurrent_marker.write_text("preserve me", encoding="utf-8")
                raise OSError("simulated copy failure")

            with mock.patch.object(
                bootstrap_module.shutil,
                "copy2",
                side_effect=fail_during_copy,
            ):
                with self.assertRaisesRegex(OSError, "simulated copy failure"):
                    bootstrap_module.install_skill(target, source_root=source)

            self.assertTrue(target.is_dir())
            self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), "partial copy")
            self.assertEqual(concurrent_marker.read_text(encoding="utf-8"), "preserve me")

    def test_main_bootstraps_copied_skill_at_install_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "installed-skill"
            with mock.patch.object(
                bootstrap_module,
                "install_skill",
                return_value=target,
            ) as install_skill:
                with mock.patch.object(bootstrap_module, "bootstrap", return_value=0) as bootstrap:
                    result = bootstrap_module.main(["--install-to", str(target)])

        self.assertEqual(result, 0)
        install_skill.assert_called_once_with(target)
        bootstrap.assert_called_once_with(
            target
            / "tools"
            / "usb-power-switch-ctl"
            / bootstrap_module.DEFAULT_VENV_NAME,
            repository_root=target,
        )

    def test_main_reports_manual_inspection_after_install_copy_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "partial-install"
            output = io.StringIO()
            with mock.patch.object(
                bootstrap_module,
                "install_skill",
                side_effect=OSError("simulated copy failure"),
            ):
                with redirect_stdout(output):
                    result = bootstrap_module.main(["--install-to", str(target)])

        self.assertEqual(result, 1)
        self.assertIn("simulated copy failure", output.getvalue())
        self.assertIn("inspect its contents", output.getvalue())
        self.assertIn("decide manually whether to keep or remove it", output.getvalue())
        self.assertIn(str(target), output.getvalue())


if __name__ == "__main__":
    unittest.main()
