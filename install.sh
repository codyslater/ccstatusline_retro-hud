#!/usr/bin/env bash
# Install retro-hud statusline for Claude Code
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
SETTINGS="$CLAUDE_DIR/settings.json"

# ── click-action handler: --handler / --handler-only (BEGIN) ──────────────
# --handler       also install the retro-hud:// reference handler
# --handler-only  install just the handler; leave the statusline alone
# Other arguments are ignored here.
WANT_HANDLER=0 HANDLER_ONLY=0 HOOKS_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --handler) WANT_HANDLER=1 ;;
        --handler-only) WANT_HANDLER=1 HANDLER_ONLY=1 ;;
        --hooks-only) HOOKS_ONLY=1 ;;
    esac
done

install_handler() {
    local dest="$CLAUDE_DIR/retro-hud-handler.sh"
    local apps="$HOME/.local/share/applications"
    local desktop="$apps/retro-hud-url-handler.desktop"
    local cfg="$HOME/.config/retro-hud/env"
    local owner features

    mkdir -p "$CLAUDE_DIR"
    cp "$SCRIPT_DIR/handler/retro-hud-handler.sh" "$dest"
    chmod +x "$dest"
    echo "Installed the click-action handler at $dest"

    if [ ! -e "$cfg" ]; then
        mkdir -p "$(dirname "$cfg")"
        cat >"$cfg" <<'EOF'
# retro-hud click-action settings, read by ~/.claude/retro-hud-handler.sh.
# The handler runs from your desktop, not your shell, so it reads these
# here. Plain KEY=VALUE lines; only these keys are read, nothing is run.
# Uncomment to change a default.
# RETRO_HUD_MODELS=opus,sonnet,haiku
# RETRO_HUD_USAGE_URL=https://claude.ai/settings/usage
EOF
        echo "Created $cfg (commented defaults)"
    fi

    if ! command -v xdg-mime &>/dev/null; then
        echo "xdg-mime not found: register the retro-hud:// URL scheme with your"
        echo "platform's tool so that it runs: $dest <url>"
    else
        owner="$(xdg-mime query default x-scheme-handler/retro-hud 2>/dev/null || true)"
        if [ -n "$owner" ]; then
            echo "retro-hud:// is already handled by $owner; left unchanged."
            echo "To use the reference handler from it, have it run: $dest <url>"
        else
            mkdir -p "$apps"
            cat >"$desktop" <<EOF
[Desktop Entry]
Type=Application
Name=retro-hud URL handler
Exec="$dest" %u
NoDisplay=true
Terminal=false
MimeType=x-scheme-handler/retro-hud;
EOF
            xdg-mime default retro-hud-url-handler.desktop x-scheme-handler/retro-hud
            if command -v update-desktop-database &>/dev/null; then
                update-desktop-database "$apps" 2>/dev/null || true
            fi
            echo "Registered retro-hud:// with $desktop"
        fi
    fi

    if command -v tmux &>/dev/null; then
        features="$(tmux show-options -s terminal-features 2>/dev/null || true)"
        if ! printf '%s\n' "$features" | grep -q hyperlinks; then
            echo "For clickable links inside tmux, add to ~/.tmux.conf:"
            echo '    set -as terminal-features "xterm*:hyperlinks"'
        fi
    fi
    echo "Click actions turn on with RETRO_HUD_ACTIONS=1 in the environment"
    echo "the statusline runs in (e.g. the env block of ~/.claude/settings.json)."
}

if [ "$WANT_HANDLER" = 1 ]; then
    install_handler
    [ "$HANDLER_ONLY" = 0 ] || exit 0
fi
# ── click-action handler (END) ────────────────────────────────────────────

if ! command -v python3 &>/dev/null; then
    echo "ERROR: retro-hud requires python3 (3.6+), which was not found on PATH." >&2
    exit 1
fi

mkdir -p "$CLAUDE_DIR"

# --hooks-only: register the presence hooks and touch nothing else — for an
# install whose statusline.py or statusline-command.sh carries local changes
# that a plain copy would overwrite.
if [ "$HOOKS_ONLY" = 1 ]; then
    set -- --hooks
else
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
fi  # not --hooks-only

# ── agent presence hooks (--hooks) ─────────────────────────────────────
# Optional: register presence-hook.sh for Stop, UserPromptSubmit and the
# permission_prompt / idle_prompt notifications, so the HUD can tell
# "waiting on a permission prompt" from "working". Re-running replaces
# our entries (idempotent) and leaves every other hook untouched.
for arg in "$@"; do
    [ "$arg" = "--hooks" ] || continue
    cp "$SCRIPT_DIR/presence-hook.sh" "$CLAUDE_DIR/presence-hook.sh"
    chmod +x "$CLAUDE_DIR/presence-hook.sh"
    BACKUP="$SETTINGS.bak.hooks.$(date +%Y%m%d%H%M%S)"
    cp "$SETTINGS" "$BACKUP"
    echo "Backed up settings to $BACKUP"
    python3 - "$SETTINGS" "$CLAUDE_DIR/presence-hook.sh" <<'PYEOF'
import json, sys
settings_path, hook = sys.argv[1], sys.argv[2]
try:
    with open(settings_path) as f:
        data = json.load(f)
except ValueError:
    sys.exit("ERROR: %s is not valid JSON; hooks not installed." % settings_path)
hooks = data.setdefault('hooks', {})
for event in list(hooks):  # drop our old entries, keep everyone else's
    groups = []
    for g in hooks[event]:
        kept = [h for h in g.get('hooks', [])
                if 'presence-hook.sh' not in str(h.get('command', ''))]
        if kept or not g.get('hooks'):
            g['hooks'] = kept
            groups.append(g)
    if groups:
        hooks[event] = groups
    else:
        del hooks[event]
for event, matcher, args in (('Stop', None, 'yours'),
                             ('UserPromptSubmit', None, 'working'),
                             ('Notification', 'permission_prompt', 'needs'),
                             ('Notification', 'idle_prompt', 'yours idle_prompt')):
    group = {'hooks': [{'type': 'command', 'command': 'bash %s %s' % (hook, args)}]}
    if matcher:
        group = dict(matcher=matcher, **group)
    hooks.setdefault(event, []).append(group)
with open(settings_path, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
print('Registered agent presence hooks in settings.json')
PYEOF
    break
done
# ── end agent presence hooks ───────────────────────────────────────────
