#!/usr/bin/env bash
# Uninstall retro-hud statusline for Claude Code
set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
SETTINGS="$CLAUDE_DIR/settings.json"

rm -f "$CLAUDE_DIR/statusline.py" "$CLAUDE_DIR/statusline-command.sh" \
      "$CLAUDE_DIR/.statusline_cache.json"

if [ -f "$SETTINGS" ] && command -v python3 &>/dev/null; then
    python3 - "$SETTINGS" <<'PYEOF'
import json, sys
settings_path = sys.argv[1]
try:
    with open(settings_path) as f:
        data = json.load(f)
except ValueError:
    sys.exit(0)
cmd = str(data.get('statusLine', {}).get('command', ''))
if 'statusline-command.sh' in cmd:
    del data['statusLine']
    with open(settings_path, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
    print('Removed statusLine from settings.json')
else:
    print('statusLine in settings.json is not retro-hud; left unchanged')
PYEOF
fi

echo "retro-hud uninstalled. Restart Claude Code to apply."
