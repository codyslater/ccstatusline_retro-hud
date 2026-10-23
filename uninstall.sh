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

# ── agent presence hooks ───────────────────────────────────────────────
# Remove what `install.sh --hooks` added (a hook pointing at a deleted
# script would error on every turn); other hooks are left untouched.
rm -f "$CLAUDE_DIR/presence-hook.sh"
if [ -f "$SETTINGS" ] && command -v python3 &>/dev/null; then
    python3 - "$SETTINGS" <<'PYEOF'
import json, sys
settings_path = sys.argv[1]
try:
    with open(settings_path) as f:
        data = json.load(f)
except ValueError:
    sys.exit(0)
hooks = data.get('hooks')
if not isinstance(hooks, dict):
    sys.exit(0)
changed = False
for event in list(hooks):
    groups = []
    for g in hooks[event]:
        kept = [h for h in g.get('hooks', [])
                if 'presence-hook.sh' not in str(h.get('command', ''))]
        changed |= len(kept) != len(g.get('hooks', []))
        if kept or not g.get('hooks'):
            g['hooks'] = kept
            groups.append(g)
    if groups:
        hooks[event] = groups
    else:
        del hooks[event]
if changed:
    if not hooks:
        del data['hooks']
    with open(settings_path, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
    print('Removed agent presence hooks from settings.json')
PYEOF
fi
# ── end agent presence hooks ───────────────────────────────────────────

echo "retro-hud uninstalled. Restart Claude Code to apply."
