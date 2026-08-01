# macOS Examples

Protocol contract: `../docs/protocol.md`

## Shell note
Use the local wrapper path directly to avoid PATH issues:
`./usb-power-switch-ctl`.
Typical USB serial node names on macOS are `/dev/cu.usbserial-*` or
`/dev/tty.usbserial-*`.

## 1) Detect port first
```bash
cd tools/usb-power-switch-ctl
ls /dev/cu.usbserial* /dev/tty.usbserial* 2>/dev/null
./usb-power-switch-ctl --list-ports --json
```
Pick the target serial port from the output (for example:
`/dev/cu.usbserial-1410`).

## 2) Dry-run first (no write)
```bash
cd tools/usb-power-switch-ctl
./usb-power-switch-ctl on --port /dev/cu.usbserial-1410 --dry-run --json
```

## 3) Execute ON
```bash
cd tools/usb-power-switch-ctl
./usb-power-switch-ctl on --port /dev/cu.usbserial-1410 --execute --yes --json
```

## 4) Verify status
```bash
cd tools/usb-power-switch-ctl
./usb-power-switch-ctl status --port /dev/cu.usbserial-1410 --json --timeout 10
```

## 5) Execute OFF
```bash
cd tools/usb-power-switch-ctl
./usb-power-switch-ctl off --port /dev/cu.usbserial-1410 --execute --yes --json
```

## 6) Cycle (3-second wait)
```bash
cd tools/usb-power-switch-ctl
./usb-power-switch-ctl power-cycle --port /dev/cu.usbserial-1410 --wait 3 --execute --yes --json
```

## Alternative: run as Python module
```bash
cd tools/usb-power-switch-ctl
python3 -m usb_power_switch_ctl status --port /dev/cu.usbserial-1410 --json
```
