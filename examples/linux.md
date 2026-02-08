# Linux Examples

## 1) Dry-run first (no write)
```bash
cd tools/y2kb-powerctl
./y2kb-powerctl on --port /dev/ttyUSB0 --dry-run --json
```

## 2) Execute ON
```bash
cd tools/y2kb-powerctl
./y2kb-powerctl on --port /dev/ttyUSB0 --execute
```

## 3) Verify status
```bash
cd tools/y2kb-powerctl
./y2kb-powerctl status --port /dev/ttyUSB0 --json
```

## 4) Cycle (3-second wait)
```bash
cd tools/y2kb-powerctl
./y2kb-powerctl cycle --port /dev/ttyUSB0 --wait 3 --execute
```
