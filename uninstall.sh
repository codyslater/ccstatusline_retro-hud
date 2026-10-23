#!/usr/bin/env bash
# Uninstall retro-hud statusline for Claude Code
set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
SETTINGS="$CLAUDE_DIR/settings.json"

rm -f "$CLAUDE_DIR/statusline.py" "$CLAUDE_DIR/statusline-command.sh" \
      "$CLAUDE_DIR/.statusline_cache.json"

# ── click-action handler (BEGIN) ──────────────────────────────────────────
# Remove the reference handler; unregister the scheme only when the
# desktop entry is the one install.sh --handler wrote (another handler
# may own retro-hud:// and is left alone). User settings are kept.
HANDLER="$CLAUDE_DIR/retro-hud-handler.sh"
APPS="$HOME/.local/share/applications"
DESKTOP="$APPS/retro-hud-url-handler.desktop"
MIMEAPPS="$HOME/.config/mimeapps.list"
rm -f "$HANDLER"
if [ -f "$DESKTOP" ] && grep -qF "Exec=\"$HANDLER\"" "$DESKTOP"; then
    rm -f "$DESKTOP"
    if [ -f "$MIMEAPPS" ]; then
        grep -v -E '^x-scheme-handler/retro-hud=retro-hud-url-handler\.desktop;?$' \
            "$MIMEAPPS" >"$MIMEAPPS.retro-hud.tmp" || true
        mv "$MIMEAPPS.retro-hud.tmp" "$MIMEAPPS"
    fi
    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database "$APPS" 2>/dev/null || true
    fi
    echo "Unregistered the retro-hud:// handler"
elif [ -f "$DESKTOP" ]; then
    echo "$DESKTOP points at another handler; left unchanged"
fi
if [ -f "$HOME/.config/retro-hud/env" ]; then
    echo "Kept your click-action settings in $HOME/.config/retro-hud/env"
fi
# ── click-action handler (END) ────────────────────────────────────────────

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
