#!/usr/bin/env python3
"""Install the bundled CLI into an isolated virtual environment safely.

This script only creates a Python virtual environment, installs the bundled
CLI, and runs its read-only serial-port discovery command.  It never selects a
device, requests elevated privileges, or sends a state-changing serial command.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence


MINIMUM_PYTHON = (3, 9)
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
CLI_PROJECT_DIR = REPOSITORY_ROOT / "tools" / "usb-power-switch-ctl"
COPY_ROOT_FILES = ("SKILL.md", "README.md", "LICENSE")
COPY_ROOT_DIRECTORIES = ("docs", "examples", "scripts", "tools")
TRANSIENT_DIRECTORY_NAMES = {
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
}


def platform_venv_name(platform: str) -> str:
    """Return the non-portable venv directory name for a supported OS."""

    if platform == "win32":
        return ".venv-windows"
    if platform == "darwin":
        return ".venv-macos"
    if platform.startswith("linux"):
        return ".venv-linux"
    raise ValueError("unsupported platform for bootstrap: {0}".format(platform))


DEFAULT_VENV_NAME = platform_venv_name(sys.platform)
DEFAULT_VENV_DIR = CLI_PROJECT_DIR / DEFAULT_VENV_NAME


@dataclass(frozen=True)
class CommandOutcome:
    """The useful, text-only result of a child process."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], Path], CommandOutcome]


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install usb-power-switch-ctl in an isolated virtual environment "
            "and run a read-only serial-port probe."
        )
    )
    parser.add_argument(
        "--venv-dir",
        type=Path,
        default=DEFAULT_VENV_DIR,
        help=(
            "virtual environment directory (default: bundled CLI {0})".format(
                DEFAULT_VENV_NAME
            )
        ),
    )
    parser.add_argument(
        "--install-to",
        type=Path,
        help=(
            "copy this skill pack to a new absolute directory, then bootstrap "
            "the copied skill there"
        ),
    )
    return parser.parse_args(argv)


def venv_python_path(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def command_runner(command: Sequence[str], cwd: Path) -> CommandOutcome:
    completed = subprocess.run(
        list(command),
        cwd=str(cwd),
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    return CommandOutcome(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def parse_probe_output(output: str) -> int:
    """Validate the CLI JSON contract and return its detected port count."""

    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError("CLI probe did not return valid JSON") from exc

    if not isinstance(payload, dict):
        raise ValueError("CLI probe JSON must be an object")
    if payload.get("ok") is not True or payload.get("command") != "list-ports":
        raise ValueError("CLI probe did not report a successful list-ports result")

    ports = payload.get("ports")
    if not isinstance(ports, list):
        raise ValueError("CLI probe JSON did not include a ports list")
    return len(ports)


def parse_python_version_output(output: str) -> tuple[int, int, int]:
    """Parse the exact JSON version tuple emitted by the venv check."""

    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError("venv Python did not return valid version JSON") from exc

    if (
        not isinstance(payload, list)
        or len(payload) != 3
        or any(type(part) is not int for part in payload)
    ):
        raise ValueError("venv Python version JSON must contain three integers")
    return tuple(payload)


def summarize_failure(outcome: CommandOutcome) -> str:
    details = (outcome.stderr or outcome.stdout).strip()
    if not details:
        return "No diagnostic output was returned."
    maximum_length = 1200
    if len(details) > maximum_length:
        return details[:maximum_length] + "\n... output truncated ..."
    return details


def print_step(status: str, message: str) -> None:
    print("[{0}] {1}".format(status, message))


def create_virtual_environment(venv_dir: Path) -> None:
    venv.EnvBuilder(with_pip=True, clear=False).create(str(venv_dir))


def copy_ignore_transient(_: str, names: List[str]) -> List[str]:
    return [
        name
        for name in names
        if name in TRANSIENT_DIRECTORY_NAMES
        or name.startswith(".venv-")
        or name.endswith(".egg-info")
        or name == ".coverage"
    ]


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def install_skill(target: Path, *, source_root: Path = REPOSITORY_ROOT) -> Path:
    """Copy only distributable skill files to a new absolute target directory."""

    target = target.expanduser()
    if not target.is_absolute():
        raise ValueError("--install-to must be an absolute path")
    if os.path.lexists(str(target)):
        raise ValueError("--install-to target already exists and will not be overwritten")

    source_root = source_root.resolve()
    target = target.resolve()
    if is_within(target, source_root):
        raise ValueError("--install-to target must be outside the source skill-pack directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.parent.is_dir():
        raise ValueError("--install-to parent path is not a directory")

    required_paths = [source_root / name for name in COPY_ROOT_FILES + COPY_ROOT_DIRECTORIES]
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise ValueError("source skill pack is missing required path(s): {0}".format(", ".join(missing)))

    try:
        target.mkdir()
    except FileExistsError as exc:
        raise ValueError("--install-to target already exists and will not be overwritten") from exc

    for name in COPY_ROOT_FILES:
        shutil.copy2(str(source_root / name), str(target / name))
    for name in COPY_ROOT_DIRECTORIES:
        shutil.copytree(
            str(source_root / name),
            str(target / name),
            ignore=copy_ignore_transient,
        )
    return target


def bootstrap(
    venv_dir: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    run_command: CommandRunner = command_runner,
    create_venv: Callable[[Path], None] = create_virtual_environment,
) -> int:
    """Create or reuse a venv, install the CLI, then run only a safe probe."""

    if sys.version_info < MINIMUM_PYTHON:
        print_step(
            "FAIL",
            "Python {0}.{1}+ is required; running {2}.{3}.".format(
                MINIMUM_PYTHON[0],
                MINIMUM_PYTHON[1],
                sys.version_info.major,
                sys.version_info.minor,
            ),
        )
        print("Next: install a supported Python version, then rerun this command.")
        return 1

    repository_root = repository_root.resolve()
    cli_project_dir = repository_root / "tools" / "usb-power-switch-ctl"
    if not cli_project_dir.is_dir():
        print_step("FAIL", "Bundled CLI project was not found: {0}".format(cli_project_dir))
        print("Next: run this script from an intact skill-pack checkout.")
        return 1

    venv_dir = venv_dir.expanduser()
    if not venv_dir.is_absolute():
        venv_dir = (repository_root / venv_dir).resolve()
    python_path = venv_python_path(venv_dir)

    print("== usb-power-switch-ctl bootstrap ==")
    print_step(
        "OK",
        "Using Python {0}.{1}.{2}.".format(
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        ),
    )

    if python_path.is_file():
        version_command = [
            str(python_path),
            "-c",
            "import json, sys; print(json.dumps(list(sys.version_info[:3])))",
        ]
        try:
            version_outcome = run_command(version_command, cli_project_dir)
        except OSError as exc:
            print_step(
                "FAIL",
                "Could not start the existing virtual environment Python: {0}".format(
                    python_path
                ),
            )
            print(str(exc))
            print(
                "Next: inspect or remove and recreate this virtual environment manually: "
                "{0}".format(venv_dir)
            )
            return 1
        if version_outcome.returncode != 0:
            print_step(
                "FAIL",
                "Existing virtual environment Python version check failed (exit={0}): {1}".format(
                    version_outcome.returncode,
                    python_path,
                ),
            )
            print(summarize_failure(version_outcome))
            print(
                "Next: inspect or remove and recreate this virtual environment manually: "
                "{0}".format(venv_dir)
            )
            return 1
        try:
            venv_version = parse_python_version_output(version_outcome.stdout)
        except ValueError as exc:
            print_step(
                "FAIL",
                "Existing virtual environment returned an invalid Python version: {0}".format(
                    python_path
                ),
            )
            print(str(exc))
            print(
                "Next: inspect or remove and recreate this virtual environment manually: "
                "{0}".format(venv_dir)
            )
            return 1
        if venv_version < MINIMUM_PYTHON:
            print_step(
                "FAIL",
                "Existing virtual environment uses Python {0}.{1}.{2}; Python {3}.{4}+ is required: "
                "{5}".format(
                    venv_version[0],
                    venv_version[1],
                    venv_version[2],
                    MINIMUM_PYTHON[0],
                    MINIMUM_PYTHON[1],
                    python_path,
                ),
            )
            print(
                "Next: remove and recreate this virtual environment manually with a supported "
                "Python: {0}".format(venv_dir)
            )
            return 1
        print_step("OK", "Reusing isolated virtual environment: {0}".format(venv_dir))
    elif venv_dir.exists():
        print_step(
            "FAIL",
            "Virtual environment directory exists but has no Python executable: {0}".format(
                venv_dir
            ),
        )
        print("Next: inspect or remove that directory manually, then rerun this command.")
        return 1
    else:
        try:
            create_venv(venv_dir)
        except (OSError, subprocess.SubprocessError) as exc:
            print_step("FAIL", "Could not create virtual environment: {0}".format(exc))
            print("Next: fix the Python environment or directory permissions, then rerun this command.")
            return 1
        if not python_path.is_file():
            print_step("FAIL", "Virtual environment creation did not produce: {0}".format(python_path))
            print("Next: inspect the Python venv installation, then rerun this command.")
            return 1
        print_step("OK", "Created isolated virtual environment: {0}".format(venv_dir))

    try:
        install = run_command(
            [
                str(python_path),
                "-m",
                "pip",
                "--disable-pip-version-check",
                "install",
                "--editable",
                str(cli_project_dir),
            ],
            cli_project_dir,
        )
    except OSError as exc:
        print_step("FAIL", "Could not start bundled CLI installation: {0}".format(exc))
        print("Next: repair or recreate the isolated virtual environment, then rerun.")
        return 1
    if install.returncode != 0:
        print_step("FAIL", "Bundled CLI installation failed (exit={0}).".format(install.returncode))
        print(summarize_failure(install))
        print("Next: check network access and Python package installation permissions, then rerun.")
        return 1
    print_step("OK", "Installed bundled CLI in the isolated virtual environment.")

    try:
        probe = run_command(
            [str(python_path), "-m", "usb_power_switch_ctl", "--list-ports", "--json"],
            cli_project_dir,
        )
    except OSError as exc:
        print_step("FAIL", "Could not start read-only serial-port probe: {0}".format(exc))
        print("Next: repair or recreate the isolated virtual environment, then rerun.")
        return 1
    if probe.returncode != 0:
        print_step("FAIL", "Read-only serial-port probe failed (exit={0}).".format(probe.returncode))
        print(summarize_failure(probe))
        print("Next: review the probe output and repair the CLI environment before selecting a port.")
        return 1

    try:
        port_count = parse_probe_output(probe.stdout)
    except ValueError as exc:
        print_step("FAIL", "Read-only serial-port probe returned an unexpected result: {0}".format(exc))
        print("Next: rerun the command and inspect the CLI output before selecting a port.")
        return 1

    print_step("OK", "Read-only serial-port probe completed; detected {0} port(s).".format(port_count))
    if port_count == 0:
        print_step("WARN", "No serial ports were detected. No device was selected or modified.")
        print("Next: connect or expose the USB serial device, then run the bootstrap again.")
    else:
        print("Next: review the reported port and run a read-only status command explicitly.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    repository_root = REPOSITORY_ROOT
    if args.install_to is not None:
        try:
            repository_root = install_skill(args.install_to)
        except (OSError, ValueError) as exc:
            print_step("FAIL", "Could not install skill pack: {0}".format(exc))
            print(
                "Next: if the target was created, inspect its contents and decide manually whether "
                "to keep or remove it: {0}".format(args.install_to.expanduser())
            )
            return 1
        print_step("OK", "Installed skill pack without overwriting files: {0}".format(repository_root))

    venv_dir = args.venv_dir
    if args.install_to is not None and venv_dir == DEFAULT_VENV_DIR:
        venv_dir = repository_root / "tools" / "usb-power-switch-ctl" / DEFAULT_VENV_NAME
    return bootstrap(venv_dir, repository_root=repository_root)


if __name__ == "__main__":
    raise SystemExit(main())
