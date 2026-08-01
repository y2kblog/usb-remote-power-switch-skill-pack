#!/usr/bin/env bash
# Keep LF line endings so WSL can execute this file from a Windows checkout.
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI_DIR="$ROOT_DIR/tools/usb-power-switch-ctl"

ok_count=0
warn_count=0
fail_count=0

say() {
  printf '%s\n' "$*"
}

mark_ok() {
  ok_count=$((ok_count + 1))
  printf '[OK] %s\n' "$1"
}

mark_warn() {
  warn_count=$((warn_count + 1))
  printf '[WARN] %s\n' "$1"
}

mark_fail() {
  fail_count=$((fail_count + 1))
  printf '[FAIL] %s\n' "$1"
}

say "== usb-power-switch-ctl WSL2 preflight =="

if grep -qi microsoft /proc/version 2>/dev/null; then
  mark_ok "Running inside WSL environment."
else
  mark_warn "Not running in WSL. This script is intended for WSL2 workflows."
fi

usbipd_cmd=""
if command -v usbipd.exe >/dev/null 2>&1; then
  usbipd_cmd="$(command -v usbipd.exe)"
elif [ -x "/mnt/c/Windows/System32/usbipd.exe" ]; then
  usbipd_cmd="/mnt/c/Windows/System32/usbipd.exe"
elif [ -x "/mnt/c/Program Files/usbipd-win/usbipd.exe" ]; then
  usbipd_cmd="/mnt/c/Program Files/usbipd-win/usbipd.exe"
fi

if [ -n "$usbipd_cmd" ]; then
  mark_ok "usbipd.exe is available from WSL: $usbipd_cmd"
else
  mark_warn "usbipd.exe is not available. Install usbipd-win on Windows host."
fi

if id -nG | tr ' ' '\n' | grep -qx "dialout"; then
  mark_ok "Current user is in dialout group."
else
  mark_fail "Current user is not in dialout group. Run: sudo usermod -aG dialout \$USER"
fi

shopt -s nullglob
serial_devices=(/dev/ttyUSB* /dev/ttyACM*)
shopt -u nullglob

if [ "${#serial_devices[@]}" -eq 0 ]; then
  mark_fail "No /dev/ttyUSB* or /dev/ttyACM* devices found."
  say "       On Windows (admin): usbipd list && usbipd attach --wsl --busid <BUSID>"
else
  mark_ok "Serial device candidates detected: ${serial_devices[*]}"
fi

cli_cmd=()
if [ -x "$CLI_DIR/.venv/bin/usb-power-switch-ctl" ]; then
  cli_cmd=("$CLI_DIR/.venv/bin/usb-power-switch-ctl")
  mark_ok "Found CLI in local venv: $CLI_DIR/.venv/bin/usb-power-switch-ctl"
elif command -v usb-power-switch-ctl >/dev/null 2>&1; then
  cli_cmd=("$(command -v usb-power-switch-ctl)")
  mark_ok "Found CLI on PATH: ${cli_cmd[0]}"
else
  mark_fail "usb-power-switch-ctl is not installed."
  say "       Install in WSL:"
  say "       cd tools/usb-power-switch-ctl"
  say "       python3 -m venv .venv && . .venv/bin/activate && python -m pip install -e ."
fi

if [ "${#cli_cmd[@]}" -gt 0 ]; then
  list_ports_output="$("${cli_cmd[@]}" --list-ports --json 2>&1)"
  list_ports_exit=$?
  if [ "$list_ports_exit" -ne 0 ]; then
    mark_fail "CLI --list-ports failed (exit=$list_ports_exit)."
    say "       Output: $list_ports_output"
  else
    mark_ok "CLI --list-ports executed successfully."
    device_count=$(printf '%s' "$list_ports_output" | grep -o '"device"' | wc -l | tr -d ' ')
    if [ "$device_count" -eq 0 ]; then
      mark_warn "CLI sees zero serial ports. Attach device to WSL with usbipd."
    else
      mark_ok "CLI reported $device_count serial port(s)."
    fi
  fi
fi

say
say "Summary: OK=$ok_count WARN=$warn_count FAIL=$fail_count"

if [ "$fail_count" -gt 0 ]; then
  say "Next: fix FAIL items first, then rerun this script."
  exit 1
fi

if [ "$warn_count" -gt 0 ]; then
  say "Next: review WARN items and proceed with usb-power-switch-ctl status test."
else
  say "Preflight passed. You can run usb-power-switch-ctl status --port <PORT> --json"
fi
