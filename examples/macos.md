# macOS Examples

Protocol contract: `../docs/protocol.md`

## 1) Dry-run first (no write)
```bash
cd tools/usb-power-switch-ctl
./usb-power-switch-ctl off --port /dev/cu.usbserial-1410 --dry-run --json
```

## 2) Execute OFF
```bash
cd tools/usb-power-switch-ctl
./usb-power-switch-ctl off --port /dev/cu.usbserial-1410 --execute
```

## 3) Verify status
```bash
cd tools/usb-power-switch-ctl
./usb-power-switch-ctl status --port /dev/cu.usbserial-1410 --json
```

## 4) Cycle (respect default rate limit)
```bash
cd tools/usb-power-switch-ctl
./usb-power-switch-ctl power-cycle --port /dev/cu.usbserial-1410 --wait 3 --execute
```
