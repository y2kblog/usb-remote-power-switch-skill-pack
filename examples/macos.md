# macOS Examples

Official product page: https://products.y2kb.com/usb-remote-power-switch/v1/

## 1) Dry-run first (no write)
```bash
cd tools/y2kb-powerctl
./y2kb-powerctl off --port /dev/cu.usbserial-1410 --dry-run --json
```

## 2) Execute OFF
```bash
cd tools/y2kb-powerctl
./y2kb-powerctl off --port /dev/cu.usbserial-1410 --execute
```

## 3) Verify status
```bash
cd tools/y2kb-powerctl
./y2kb-powerctl status --port /dev/cu.usbserial-1410 --json
```

## 4) Cycle (respect default rate limit)
```bash
cd tools/y2kb-powerctl
./y2kb-powerctl power-cycle --port /dev/cu.usbserial-1410 --wait 3 --execute
```
