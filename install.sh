#!/usr/bin/env bash
# Install retro-hud statusline for Claude Code
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
SETTINGS="$CLAUDE_DIR/settings.json"

if ! command -v python3 &>/dev/null; then
    echo "ERROR: retro-hud requires python3 (3.6+), which was not found on PATH." >&2
    exit 1
fi

mkdir -p "$CLAUDE_DIR"

cp "$SCRIPT_DIR/statusline.py" "$CLAUDE_DIR/statusline.py"
cp "$SCRIPT_DIR/statusline-command.sh" "$CLAUDE_DIR/statusline-command.sh"
chmod +x "$CLAUDE_DIR/statusline-command.sh"

if [ -f "$SETTINGS" ]; then
    BACKUP="$SETTINGS.bak.$(date +%Y%m%d%H%M%S)"
    cp "$SETTINGS" "$BACKUP"
    echo "Backed up settings to $BACKUP"
    python3 - "$SETTINGS" "$CLAUDE_DIR" <<'PYEOF'
import json, sys
settings_path, claude_dir = sys.argv[1], sys.argv[2]
try:
    with open(settings_path) as f:
        data = json.load(f)
except ValueError:
    sys.exit("ERROR: %s is not valid JSON; fix it and re-run, or add the "
             "statusLine block manually (see README)." % settings_path)
data['statusLine'] = {
    'type': 'command',
    'command': 'bash %s/statusline-command.sh' % claude_dir,
    'refreshInterval': 5,
}
with open(settings_path, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
print('Updated existing settings.json')
PYEOF
else
    cat > "$SETTINGS" <<EOF
{
  "statusLine": {
    "type": "command",
    "command": "bash $CLAUDE_DIR/statusline-command.sh",
    "refreshInterval": 5
  }
}
EOF
    echo "Created settings.json"
fi

echo "Installed $(python3 "$CLAUDE_DIR/statusline.py" --version). Restart Claude Code to activate."
echo "Preview it any time with: python3 $CLAUDE_DIR/statusline.py --demo"
