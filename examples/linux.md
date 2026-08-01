# Linux Examples

Protocol contract: `../docs/protocol.md`

## 1) Dry-run first (no write)
```bash
cd tools/usb-power-switch-ctl
./usb-power-switch-ctl on --port /dev/ttyUSB0 --dry-run --json
```

## 2) Execute ON
```bash
cd tools/usb-power-switch-ctl
./usb-power-switch-ctl on --port /dev/ttyUSB0 --execute
```

## 3) Verify status
```bash
cd tools/usb-power-switch-ctl
./usb-power-switch-ctl status --port /dev/ttyUSB0 --json
```

## 4) Cycle (3-second wait)
```bash
cd tools/usb-power-switch-ctl
./usb-power-switch-ctl power-cycle --port /dev/ttyUSB0 --wait 3 --execute
```
