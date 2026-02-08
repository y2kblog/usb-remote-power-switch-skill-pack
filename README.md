# USB Remote Power Switch Skill Pack

Skill pack for safe USB serial control of **Y2KB-037 USB Remote Power Switch**.

## Official product page
- https://products.y2kb.com/usb-remote-power-switch/v1/

## Included
- `SKILL.md` for Codex / Claude Code skill usage
- `tools/y2kb-powerctl/` CLI (Python + pyserial, minimal dependency)
- `examples/` for Linux, macOS, Windows
- Unit tests for argument parsing, dry-run safety, and JSON output

## Quick start
```bash
cd tools/y2kb-powerctl
python3 -m pip install -e .
y2kb-powerctl --list-ports
y2kb-powerctl status --port <PORT> --json
y2kb-powerctl on --port <PORT> --dry-run --json
```

## Safety defaults
- `--dry-run` by default
- Side-effect operations require explicit `--execute`
- Pre-execution status check and confirmation prompt
- Cycle command rate-limiting
