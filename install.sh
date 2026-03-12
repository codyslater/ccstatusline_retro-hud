#!/usr/bin/env bash
# Install retro-hud statusline for Claude Code
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"

mkdir -p "$CLAUDE_DIR"

# Copy statusline files
cp "$SCRIPT_DIR/statusline.py" "$CLAUDE_DIR/statusline.py"
cp "$SCRIPT_DIR/statusline-command.sh" "$CLAUDE_DIR/statusline-command.sh"
chmod +x "$CLAUDE_DIR/statusline-command.sh"

# Add statusLine config to settings.json (merge if exists)
SETTINGS="$CLAUDE_DIR/settings.json"
if [ -f "$SETTINGS" ]; then
    # Check if python3 available for JSON merge
    if command -v python3 &>/dev/null; then
        python3 - "$SETTINGS" "$CLAUDE_DIR" <<'PYEOF'
import json, sys
settings_path = sys.argv[1]
claude_dir = sys.argv[2]
with open(settings_path) as f:
    data = json.load(f)
data['statusLine'] = {
    'type': 'command',
    'command': f'bash {claude_dir}/statusline-command.sh'
}
with open(settings_path, 'w') as f:
    json.dump(data, f, indent=2)
print('Updated existing settings.json')
PYEOF
    else
        echo "WARNING: python3 not found, cannot merge settings.json"
        echo "Add this manually to $SETTINGS:"
        echo '  "statusLine": {"type": "command", "command": "bash ~/.claude/statusline-command.sh"}'
    fi
else
    cat > "$SETTINGS" << 'EOF'
{
  "statusLine": {
    "type": "command",
    "command": "bash ~/.claude/statusline-command.sh"
  }
}
EOF
    echo "Created settings.json"
fi

echo "retro-hud installed. Restart Claude Code to activate."
