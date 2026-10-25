#!/usr/bin/env bash
# retro-hud reference handler for retro-hud:// click actions.
#
# Your desktop runs this with ONE argument, the clicked URL:
#
#   retro-hud://<action>?pane=<tmux pane id>[&sock=<tmux socket>]
#
# actions: model effort ctx cost diff usage agent card (see README, "Click
# actions"; `card` is the creature's status card, `agent` its menu). The URL is checked against a strict whitelist and every query
# value is validated before anything runs; rejected URLs are logged to
# ~/.cache/retro-hud/handler.log and ignored. Any program can print a
# link, so a URL is never trusted to pick the target: the pane must be
# the clicking client's active pane and run `claude`, and the diff runs
# in the directory tmux reports for that pane. Menu items call this script
# back in an internal form that carries only validated tokens:
#
#   retro-hud-handler.sh do [-S <sock>] send <pane> <command> [<arg>]
#   retro-hud-handler.sh do [-S <sock>] confirm-clear <pane>
#   retro-hud-handler.sh do [-S <sock>] agent <pane> wave|quiet|sprites|reroll|status
#   retro-hud-handler.sh do [-S <sock>] agent <pane> sprite <set or family>|default
#   retro-hud-handler.sh do [-S <sock>] agent <pane> sizes
#   retro-hud-handler.sh do [-S <sock>] agent <pane> size tiny|big|tall|default
#
# Settings come from the environment or, because a desktop-launched
# handler never reads your shell rc files, from ~/.config/retro-hud/env:
# plain KEY=VALUE lines, read line by line (never sourced). Keys:
#   RETRO_HUD_MODELS      comma list for the model menu (opus,sonnet,haiku)
#   RETRO_HUD_USAGE_URL   page the rate-limit gauges open
#   RETRO_HUD_AGENT_NAME  title of the agent menu (default "agent")
#   RETRO_HUD_CACHE_DIR   the HUD's presence cache, if you moved it
#                         (default ~/.cache/retro-hud)
#
# Inside a tmux right-click binding (README, "Right-click in tmux") the
# binding runs this script synchronously with two more variables:
#   RETRO_HUD_CLIENT     the clicking client's tty (the menu's -c)
#   RETRO_HUD_MENU_FILE  an absolute <path>.tmux: this script removes it,
#                        then a menu action WRITES its one `display-menu`
#                        line there instead of running it; the binding
#                        `source-file`s it next, so the menu runs with the
#                        press's mouse event — it opens at the pointer,
#                        takes clicks, and survives the button's release.
#                        (A menu run from outside the binding has no mouse
#                        event; tmux 3.4 then makes it keyboard-only and
#                        the right button's own release closes it.)
# A slow action (the diff popup) is detached when that variable is set,
# so the binding never waits on it.
#
# Extension point: if ~/.claude/retro-hud-handler.local.sh exists it is
# sourced first, with the same arguments; it may handle anything itself
# and `exit`, otherwise the built-in actions below run.
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
unset TMUX

LOG_DIR="$HOME/.cache/retro-hud"
CONFIG="$HOME/.config/retro-hud/env"
LOCAL_EXT="$HOME/.claude/retro-hud-handler.local.sh"
LEVELS="low medium high xhigh max"
DEFAULT_MODELS="opus,sonnet,haiku"
DEFAULT_USAGE_URL="https://claude.ai/settings/usage"
NOTE="(types into the composer)"
SELF="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")"

log() {
    { mkdir -p "$LOG_DIR" && printf '%s %s\n' "$(date +%Y-%m-%dT%H:%M:%S)" "$*" \
        >>"$LOG_DIR/handler.log"; } 2>/dev/null || true
}

reject() {
    log "reject: $*"
    exit 0
}

# ── the right-click binding's two variables (see the header) ──
MENU_FILE=""
if [ -n "${RETRO_HUD_MENU_FILE:-}" ]; then
    if [[ $RETRO_HUD_MENU_FILE =~ ^/[A-Za-z0-9._/-]+\.tmux$ ]]; then
        MENU_FILE=$RETRO_HUD_MENU_FILE
        rm -f "$MENU_FILE"    # a stale menu must never be sourced again
    else
        log "RETRO_HUD_MENU_FILE ignored: not a plain absolute .tmux path"
    fi
fi
BOUND_CLIENT=""
if [ -n "${RETRO_HUD_CLIENT:-}" ]; then
    if [[ $RETRO_HUD_CLIENT =~ ^/dev/[A-Za-z0-9/._-]+$ ]]; then
        BOUND_CLIENT=$RETRO_HUD_CLIENT
    else
        log "RETRO_HUD_CLIENT ignored: not a tty path"
    fi
fi

# A right-click while one of our popups (cloud, card, diff) is up closes it
# instead of opening another (so the click that opened it can close it). Each popup's command keeps a marker file
# for its client while it runs; inside the binding the handler then writes
# `display-popup -C` for the binding to run. A stale marker (older than an
# hour) is ignored. A local extension's popups keep the same marker.
POPUP_MARK=""
if [ -n "$BOUND_CLIENT" ]; then
    POPUP_MARK="$LOG_DIR/popup-${BOUND_CLIENT//\//_}"
    if [ -n "$MENU_FILE" ] && [ -f "$POPUP_MARK" ]; then
        if [ -n "$(find "$POPUP_MARK" -mmin -60 2>/dev/null)" ]; then
            printf "display-popup -C -c '%s'\n" "$BOUND_CLIENT" >"$MENU_FILE.tmp" && mv -f "$MENU_FILE.tmp" "$MENU_FILE"
            rm -f "$POPUP_MARK"
            log "popup up on $BOUND_CLIENT: this click closes it"
            exit 0
        fi
        rm -f "$POPUP_MARK"
    fi
fi
# What a popup's runner does after printing: wait for one key — or one click. With
# mouse reporting on, a click inside the popup arrives as an SGR sequence: a PRESS
# closes it like a key, a RELEASE (…m) is ignored, so the opening click's own release
# never closes it however long the button is held. tmux hands a click
# outside a popup to nobody, so the popup is centred on the pointer: the second click
# on the same spot lands inside it.
POPUP_READ="printf '\\033[?1000h\\033[?1006h'
while IFS= read -rsn1 k </dev/tty; do
  if [ \"\$k\" = \$'\\e' ]; then
    s=''; while IFS= read -rsn1 -t 0.05 c </dev/tty; do s+=\"\$c\"; case \"\$c\" in M|m) break ;; esac; done
    case \"\$s\" in '[<'*m) continue ;; esac
    k=''
  fi
  break
done
printf '\\033[?1006l\\033[?1000l'
"
popup_guard() {  # the lines a popup's runner starts with: keep the marker while it runs
    [ -n "$POPUP_MARK" ] || return 0
    printf 'touch %s\ntrap %s EXIT\n' "$(tmq "$POPUP_MARK")" "$(tmq "rm -f '$POPUP_MARK'")"
}

if [ -f "$LOCAL_EXT" ]; then
    # It sees "$@"; returning (with any status) falls through to the
    # built-in actions, `exit` ends the click.
    # shellcheck source=/dev/null
    . "$LOCAL_EXT" "$@" || true
fi

# ── settings: environment first, then the config file, then defaults ──
cfg_models="" cfg_usage_url="" cfg_agent_name="" cfg_cache_dir="" cfg_home_session="" cfg_remote_dir=""
if [ -f "$CONFIG" ]; then
    n=0
    while IFS= read -r line || [ -n "$line" ]; do
        n=$((n + 1))
        [[ $line =~ ^[[:space:]]*(#|$) ]] && continue
        if [[ $line =~ ^(RETRO_HUD_MODELS|RETRO_HUD_USAGE_URL|RETRO_HUD_AGENT_NAME|RETRO_HUD_CACHE_DIR|RETRO_HUD_HOME_SESSION|RETRO_HUD_REMOTE_DIR)=(.*)$ ]]; then
            key=${BASH_REMATCH[1]} val=${BASH_REMATCH[2]}
            if [[ $val =~ ^\"(.*)\"$ || $val =~ ^\'(.*)\'$ ]]; then
                val=${BASH_REMATCH[1]}
            fi
            case $key in
                RETRO_HUD_MODELS) cfg_models=$val ;;
                RETRO_HUD_USAGE_URL) cfg_usage_url=$val ;;
                RETRO_HUD_AGENT_NAME) cfg_agent_name=$val ;;
                RETRO_HUD_CACHE_DIR) cfg_cache_dir=$val ;;
                RETRO_HUD_HOME_SESSION) cfg_home_session=$val ;;
                RETRO_HUD_REMOTE_DIR) cfg_remote_dir=$val ;;
            esac
        else
            log "config: ignored line $n of $CONFIG"
        fi
    done <"$CONFIG"
fi

MODEL_RE='^[][A-Za-z0-9._:-]+$'  # e.g. opus, sonnet, opus[1m], claude-x-1.5
valid_model() { [[ $1 =~ $MODEL_RE ]]; }
valid_level() { [[ " $LEVELS " == *" $1 "* ]] && [[ $1 =~ ^[a-z]+$ ]]; }
safe_path() { [[ $1 =~ ^/[A-Za-z0-9._/-]+$ ]]; }

MODELS=()
IFS=',' read -ra _raw <<<"${RETRO_HUD_MODELS:-${cfg_models:-$DEFAULT_MODELS}}"
for m in "${_raw[@]}"; do
    m="${m#"${m%%[![:space:]]*}"}"
    m="${m%"${m##*[![:space:]]}"}"
    if valid_model "$m"; then MODELS+=("$m"); elif [ -n "$m" ]; then log "config: bad model ignored"; fi
done
[ "${#MODELS[@]}" -gt 0 ] || IFS=',' read -ra MODELS <<<"$DEFAULT_MODELS"

USAGE_URL="${RETRO_HUD_USAGE_URL:-${cfg_usage_url:-$DEFAULT_USAGE_URL}}"
if ! [[ $USAGE_URL =~ ^https?://[^[:space:][:cntrl:]]+$ ]]; then
    log "config: RETRO_HUD_USAGE_URL is not an http(s) URL; using the default"
    USAGE_URL=$DEFAULT_USAGE_URL
fi

# ── tmux helpers ──
SOCK=""
tm() {
    if [ -n "$SOCK" ]; then tmux -S "$SOCK" "$@"; else tmux "$@"; fi
}

# The handler has no $TMUX: the clicking client is the one the binding
# named, else the attached client with the newest activity.
newest_client() {
    tm list-clients -F '#{client_activity} #{client_tty}' 2>/dev/null |
        sort -rn | head -n 1 | cut -d' ' -f2-
}

need_client() {
    if [ -n "$BOUND_CLIENT" ]; then
        CLIENT=$BOUND_CLIENT
        return 0
    fi
    CLIENT=$(newest_client) || CLIENT=""
    if [ -z "$CLIENT" ]; then
        log "no tmux client found (is the tmux server running?)"
        exit 0
    fi
}

# One token for tmux's command parser: single quotes keep it literal (no
# comment, no $ or ~ expansion, no escapes); a quote inside ends the
# token, escapes one quote and reopens, as in the shell.
tmq() {
    printf "'%s'" "${1//\'/\'\\\'\'}"
}

# A menu for the binding to run: one display-menu line in the menu file.
write_menu_file() {  # title, then name/key/command triples
    local title=$1 a
    shift
    {
        printf "display-menu -O -c %s -T %s -x M -y '#{popup_mouse_y}' --" "$(tmq "$CLIENT")" "$(tmq "$title")"
        for a in "$@"; do printf ' %s' "$(tmq "$a")"; done
        printf '\n'
    } >"$MENU_FILE.tmp" && mv -f "$MENU_FILE.tmp" "$MENU_FILE" || {
        rm -f "$MENU_FILE.tmp"
        log "menu file write failed: $MENU_FILE"
    }
}

# A menu item re-enters this script; every token is pre-validated, so the
# single quotes below never need escaping.
menu_cmd() {
    local verb=$1 pane=$2
    shift 2
    local s="run-shell -b \"'$SELF' do"
    [ -z "$SOCK" ] || s+=" -S '$SOCK'"
    s+=" $verb '$pane'"
    [ $# -eq 0 ] || s+=" $*"
    printf '%s"' "$s"
}

show_menu() {  # title, then name/key/command triples
    local title=$1
    shift
    if ! safe_path "$SELF"; then  # menu items embed it between single quotes
        log "menu refused: unsafe handler path $(printf '%q' "$SELF"); install it under a plain path"
        exit 0
    fi
    need_client
    if [ -n "$MENU_FILE" ]; then
        # The binding sources this line next, inside its own command chain, so the menu has
        # the press's mouse event: -x M centres it on the pointer and -y '#{popup_mouse_y}'
        # (the row below the box) stands it ABOVE the pointer, where the button's release
        # lands outside it (-O: a release outside is ignored; a press outside, Esc, q close).
        write_menu_file "$title" "$@"
        return 0
    fi
    # No binding behind this click (a Ctrl+click through the desktop): run it here. Without
    # a mouse event tmux makes this a keyboard menu (keys, Esc, q); it waits while it is up.
    tm display-menu -O -c "$CLIENT" -x C -y C -T "$title" "$@" || log "display-menu failed"
}

# Compose the slash command for a validated (command, arg) pair.
slash_text() {
    case "$1:$#" in
        model:1) printf '/model' ;;
        model:2) valid_model "$2" && printf '/model %s' "$2" ;;
        effort:2) valid_level "$2" && printf '/effort %s' "$2" ;;
        compact:1 | context:1 | clear:1 | cost:1) printf '/%s' "$1" ;;
        *) return 1 ;;
    esac
}

# A link can be printed by anything in any pane, so it may only act on the
# pane the user is looking at: the clicking client's active pane.
require_active_pane() {
    local pane=$1 active
    need_client
    active=$(tm display -p -c "$CLIENT" '#{pane_id}' 2>/dev/null) || active=""
    if [ "$active" != "$pane" ]; then
        log "refused: link targets $pane, active pane is ${active:-?}"
        tm display-message -c "$CLIENT" "retro-hud: link targets a different pane; ignored" || true
        exit 0
    fi
}

# Does the pane run Claude? Its foreground command, or (a wrapper script
# in front: a launcher that execs nothing) a direct child named claude.
pane_runs_claude() {  # pane -> 0/1; sets CURRENT for the log
    local pane=$1 pid
    CURRENT=$(tm display -p -t "$pane" '#{pane_current_command}' 2>/dev/null) || CURRENT=""
    [ "$CURRENT" = claude ] && return 0
    pid=$(tm display -p -t "$pane" '#{pane_pid}' 2>/dev/null) || pid=""
    [[ $pid =~ ^[0-9]+$ ]] && pgrep -P "$pid" -x claude >/dev/null 2>&1
}

send_slash() {  # pane, command, [arg]
    local pane=$1 text current
    shift
    text=$(slash_text "$@") || reject "send: $(printf '%q ' "$@")"
    require_active_pane "$pane"
    if ! pane_runs_claude "$pane"; then
        current=$CURRENT
        log "send refused: pane $pane runs '${current:-?}', not claude"
        CLIENT=$(newest_client) || CLIENT=""
        if [ -n "$CLIENT" ]; then
            tm display-message -c "$CLIENT" "retro-hud: that pane is no longer running Claude" || true
        fi
        return 0
    fi
    tm send-keys -t "$pane" -l "$text" && tm send-keys -t "$pane" Enter ||
        log "send-keys to $pane failed"
}

# ── agent helpers: BEGIN ──
# The agent menu talks to the HUD through its presence cache, never to
# Claude: the state file (<sid>.state.json, keys mute_until, sprite, size
# and seed; the HUD's `creature` key says the pixel creature is on)
# and the events channel (<sid>.events.jsonl). The HUD records which
# session a pane shows in <cache>/pane-<N>.sid (pane %N) while click
# actions are on, so the session is found from the pane, never the URL.
SPRITE_SETS="alien cat robot ghost"
FAMILIES="blob beast alien bot robot"  # the pixel creature's families
SIZES="tiny big tall"            # the pixel creature's sizes
QUIET_S=3600
WAVE_TTL=10
AGENT_NAME=${RETRO_HUD_AGENT_NAME:-$cfg_agent_name}
if ! [[ $AGENT_NAME =~ ^[A-Za-z0-9][A-Za-z0-9\ ._-]{0,23}$ ]]; then
    [ -z "$AGENT_NAME" ] || log "config: RETRO_HUD_AGENT_NAME must be letters, digits, space . _ - (max 24); ignored"
    AGENT_NAME=agent
fi

# Same resolution as the HUD: RETRO_HUD_CACHE_DIR, else ~/.cache/retro-hud,
# else (when that doesn't exist) the HUD's own /tmp/retro-hud-<uid>.
presence_cache() {
    local d=${RETRO_HUD_CACHE_DIR:-$cfg_cache_dir} t
    if [ -z "$d" ]; then
        d="$HOME/.cache/retro-hud"
        t="/tmp/retro-hud-$(id -u)"
        if [ ! -d "$d" ] && [ -d "$t" ] && [ -O "$t" ]; then d=$t; fi
    fi
    if [[ $d != /* || $d == *[[:cntrl:]]* ]]; then
        log "agent: RETRO_HUD_CACHE_DIR must be an absolute path"
        return 1
    fi
    printf '%s' "$d"
}

# The remote feed: RETRO_HUD_REMOTE_DIR, else <cache>/remote. Every <host>.json
# there (written by whatever sync you run: ssh, rsync, a cron) lists the Claude
# sessions on another machine; the session list shows them as ⌁ host:name and a
# click opens the file's `open` command (default: ssh + tmux attach) in a wrapper
# session here. A file older than 15 minutes is ignored: its sync is gone.
remote_dir() {
    local d=${RETRO_HUD_REMOTE_DIR:-$cfg_remote_dir} c
    if [ -z "$d" ]; then
        c=$(presence_cache) || return 1
        d="$c/remote"
    fi
    if [[ $d != /* || $d == *[[:cntrl:]]* ]]; then
        log "sessions: RETRO_HUD_REMOTE_DIR must be an absolute path"
        return 1
    fi
    printf '%s' "$d"
}

# Python does the JSON: an atomic read-modify-write that keeps every key
# it doesn't own, and the status line from the snapshot. Arguments are
# validated tokens; nothing from the files is ever run or echoed raw.
STATE_PY='
import json, math, os, sys, tempfile, time
path, op, args = sys.argv[1], sys.argv[2], sys.argv[3:]
try:
    with open(path) as f:
        obj = json.loads(f.read(1 << 20))
except FileNotFoundError:
    obj = {}
except (OSError, ValueError):
    sys.exit("state file unreadable or not JSON; left alone")
if not isinstance(obj, dict):
    sys.exit("state file is not a JSON object; left alone")
if op == "status":
    def num(k):
        v = obj.get(k)
        ok = isinstance(v, (int, float)) and not isinstance(v, bool)
        return v if ok and math.isfinite(v) else None
    label = {"working": "working", "yours": "your turn", "needs": "needs you",
             "error": "error", "idle": "idle", "asleep": "asleep"}.get(obj.get("state"))
    if label is None:
        print(args[0] + ": no status yet")
        sys.exit(0)
    since = num("since")
    if since is not None:
        age = max(0, int(time.time() - since))
        label += " for " + ("%ds" % age if age < 60 else "%dm" % (age // 60) if age < 3600
                            else "%dh%02dm" % (age // 3600, age % 3600 // 60))
    ctx, lim, cost = num("ctx_pct"), num("limit_pct"), num("cost")
    print(" · ".join([args[0] + ": " + label,
                      "ctx " + ("%d%%" % ctx if ctx is not None else "?"),
                      "limit " + ("%d%%" % lim if lim is not None else "?"),
                      "$%.2f" % cost if cost is not None else "$?"]))
    sys.exit(0)
if op == "card":
    def num(k):
        v = obj.get(k)
        ok = isinstance(v, (int, float)) and not isinstance(v, bool)
        return v if ok and math.isfinite(v) else None
    def span(sec):
        sec = int(sec)
        return "%ds" % sec if sec < 60 else "%dm" % (sec // 60) if sec < 3600 else "%dh%02dm" % (sec // 3600, sec % 3600 // 60)
    def text(k, n=40):
        v = obj.get(k)
        return "".join(ch for ch in v if ch.isprintable())[:n] if isinstance(v, str) else None
    label = {"working": "working", "yours": "your turn", "needs": "needs you",
             "error": "error", "idle": "idle", "asleep": "asleep"}.get(obj.get("state"))
    head = args[0] + " · " + (label or "no status yet")
    since = num("since")
    if label and since is not None:
        head += " for " + span(max(0, time.time() - since))
    print(head)
    model, effort = text("model"), text("effort", 12)
    if model or effort:
        print(" · ".join(x for x in (model, "effort " + effort if effort else None) if x))
    ctx, lim, cost, dur = num("ctx_pct"), num("limit_pct"), num("cost"), num("dur_s")
    gauges = [("context %d%%" % ctx) if ctx is not None else None,
              ("limit %d%%" % lim) if lim is not None else None,
              ("$%.2f" % cost) if cost is not None else None,
              span(dur) if dur is not None else None]
    if any(gauges):
        print(" · ".join(g for g in gauges if g))
    add, rem, d = num("lines_add"), num("lines_del"), text("dir")
    parts = [("+%d/-%d" % (add, rem)) if add is not None and rem is not None else None,
             ("dir " + d) if d else None]
    if any(parts):
        print(" · ".join(x for x in parts if x))
    sys.exit(0)
if op == "creature":
    print("on" if isinstance(obj.get("creature"), str) else "off")
    sys.exit(0)
if op == "mute":
    obj["mute_until"] = int(time.time()) + int(args[0])
elif op == "reroll":
    obj["seed"] = int.from_bytes(os.urandom(4), "big")
elif op == "sprite" and args[0] == "default":
    obj.pop("sprite", None)
elif op == "sprite":
    obj["sprite"] = args[0]
elif op == "size" and args[0] == "default":
    obj.pop("size", None)
elif op == "size":
    obj["size"] = args[0]
else:
    sys.exit("unknown op")
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".",
                           prefix=os.path.basename(path) + ".", suffix=".tmp")
try:
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)
except BaseException:
    os.unlink(tmp)
    raise
if op == "reroll":
    print(obj["seed"])
'

state_py() {  # op, [arg]; stdout is the result, errors go to the log
    local err=/dev/null
    if mkdir -p "$LOG_DIR" 2>/dev/null && [ -w "$LOG_DIR" ]; then err="$LOG_DIR/handler.log"; fi
    python3 -I -c "$STATE_PY" "$STATE_FILE" "$@" 2>>"$err"
}

# Resolve the clicked pane to its session: it must be the clicking
# client's active pane, run claude, and have a session map from the HUD.
agent_target() {
    local pane=$1 current map sid=""
    require_active_pane "$pane"
    if ! pane_runs_claude "$pane"; then
        current=$CURRENT
        log "agent refused: pane $pane runs '${current:-?}', not claude"
        tm display-message -c "$CLIENT" "retro-hud: that pane is no longer running Claude" || true
        exit 0
    fi
    CACHE=$(presence_cache) || exit 0
    map="$CACHE/pane-${pane#%}.sid"
    [ ! -f "$map" ] || sid=$(head -c 256 "$map" 2>/dev/null) || sid=""
    if ! [[ $sid =~ ^[A-Za-z0-9_-]{1,128}$ ]]; then
        log "agent: no session mapped for pane $pane in $CACHE"
        tm display-message -c "$CLIENT" \
            "retro-hud: no agent presence for this pane yet (needs RETRO_HUD_ACTIONS=1 and a transcript)" || true
        exit 0
    fi
    STATE_FILE="$CACHE/$sid.state.json"
    EVENTS_FILE="$CACHE/$sid.events.jsonl"
}

# Is the pixel creature on? The HUD records it in the state file, since
# the handler never sees the statusline's environment.
creature_on() { [ "$(state_py creature 2>/dev/null)" = on ]; }

agent_menu() {
    local pane=$1 extra=() card_url
    if creature_on; then
        extra=("size ▸" z "$(menu_cmd agent "$pane" sizes)"
               "reroll" r "$(menu_cmd agent "$pane" reroll)")
    fi
    # the card by its public URL (a local extension may answer it), so it is reachable from
    # this menu when a narrow terminal has dropped the creature itself
    card_url="retro-hud://card?pane=%25${pane#%}"
    [ -z "$SOCK" ] || card_url+="&sock=$SOCK"
    show_menu "$AGENT_NAME" \
        "status card" c "run-shell -b \"'$SELF' '$card_url'\"" \
        "wave" w "$(menu_cmd agent "$pane" wave)" \
        "quiet 1h" h "$(menu_cmd agent "$pane" quiet)" \
        "sprite ▸" s "$(menu_cmd agent "$pane" sprites)" \
        ${extra[@]+"${extra[@]}"} \
        "status" i "$(menu_cmd agent "$pane" status)"
}

agent_do() {  # pane, subcommand, [arg] (validated by the caller)
    local pane=$1 sub=$2 msg items=() n i=0
    agent_target "$pane"
    case $sub in
        wave)
            printf '{"ts":%s,"text":"wave","ttl":%s}\n' "$(date +%s)" "$WAVE_TTL" \
                >>"$EVENTS_FILE" 2>/dev/null || log "agent: cannot append to the events file"
            ;;
        quiet) state_py mute "$QUIET_S" || log "agent: quiet failed" ;;
        sprite) state_py sprite "$3" || log "agent: sprite failed" ;;
        size) state_py size "$3" || log "agent: size failed" ;;
        sizes)
            for n in $SIZES default; do
                i=$((i + 1))
                items+=("$n" "$i" "$(menu_cmd agent "$pane" size "$n")")
            done
            show_menu "$AGENT_NAME: size" "${items[@]}"
            ;;
        reroll)
            n=$(state_py reroll) || n=""
            if [[ $n =~ ^[0-9]+$ ]]; then
                tm display-message -c "$CLIENT" \
                    "$AGENT_NAME: new look; pin it with RETRO_HUD_CREATURE_SEED=$n" || true
            else
                log "agent: reroll failed"
            fi
            ;;
        sprites)
            local names=$SPRITE_SETS
            if creature_on; then names=$FAMILIES; fi
            for n in $names default; do
                i=$((i + 1))
                items+=("$n" "$i" "$(menu_cmd agent "$pane" sprite "$n")")
            done
            show_menu "$AGENT_NAME: sprite" "${items[@]}"
            ;;
        status)
            msg=$(state_py status "$AGENT_NAME") || msg="$AGENT_NAME: status unavailable"
            tm display-message -c "$CLIENT" "${msg//#/}" || true
            ;;
    esac
}
# ── agent helpers: END ──

# ── internal form, used by menu items ──
if [ "${1-}" = "do" ]; then
    shift
    if [ "${1-}" = "-S" ]; then
        [ $# -ge 2 ] && safe_path "$2" && [ -S "$2" ] || reject "do: bad socket"
        SOCK=$2
        shift 2
    fi
    [ $# -ge 2 ] && [[ $2 =~ ^%[0-9]+$ ]] || reject "do: $(printf '%q ' "$@")"
    verb=$1 pane=$2
    shift 2
    case $verb in
        send)
            [ $# -ge 1 ] || reject "do send: no command"
            send_slash "$pane" "$@"
            ;;
        confirm-clear)
            [ $# -eq 0 ] || reject "do confirm-clear: extra arguments"
            show_menu "really /clear this session? $NOTE" \
                "no, keep it" n "" \
                "yes, /clear" y "$(menu_cmd send "$pane" clear)"
            ;;
        agent)
            case "${1-}:$#" in
                wave:1 | quiet:1 | sprites:1 | sizes:1 | reroll:1 | status:1) ;;
                size:2) [[ " $SIZES default " == *" $2 "* && $2 =~ ^[a-z]+$ ]] ||
                    reject "do agent size: $(printf '%q' "$2")" ;;
                sprite:2) [[ " $SPRITE_SETS $FAMILIES default " == *" $2 "* && $2 =~ ^[a-z]+$ ]] ||
                    reject "do agent sprite: $(printf '%q' "$2")" ;;
                *) reject "do agent: $(printf '%q ' "$@")" ;;
            esac
            agent_do "$pane" "$@"
            ;;
        *) reject "do: unknown verb $(printf '%q' "$verb")" ;;
    esac
    exit 0
fi

# ── URL form ──
[ $# -eq 1 ] || reject "expected one argument, got $#"
URL=$1
re='^retro-hud://(model|effort|ctx|cost|diff|usage|agent|card|sessions|needs|switch|home|back)(\?([A-Za-z0-9_=&%.:/~+-]*))?$'
[[ $URL =~ $re ]] || reject "$(printf '%q' "$URL")"
ACTION=${BASH_REMATCH[1]}
QUERY=${BASH_REMATCH[3]}
[[ $QUERY != *%00* ]] || reject "NUL in query"

urldecode() {  # the trailing x keeps decoded trailing newlines visible
    local s=${1//%/\\x}
    printf '%b' "$s"
    printf x
}

PANE="" CUR="" TO="" has_sock=0
IFS='&' read -ra pairs <<<"$QUERY"
for pair in "${pairs[@]}"; do
    [[ $pair == *=* ]] || continue
    k=${pair%%=*}
    v=$(urldecode "${pair#*=}")
    v=${v%x}
    case $k in
        pane) PANE=$v ;;
        sock) SOCK=$v has_sock=1 ;;
        cur) CUR=$v ;;
        to) TO=$v ;;      # switch: the tmux session to switch the client to
        # unknown keys (including a `cwd`) are ignored, so the contract can
        # grow; directories always come from tmux, never from a link
        *) ;;
    esac
done

case $ACTION in usage | sessions | needs | switch | home | back) need_pane=0 ;; *) need_pane=1 ;; esac
if [ "$need_pane" = 1 ] || [ -n "$PANE" ]; then
    [[ $PANE =~ ^%[0-9]+$ ]] || reject "$ACTION: bad pane $(printf '%q' "$PANE")"
fi
if [ "$has_sock" = 1 ]; then
    safe_path "$SOCK" && [ -S "$SOCK" ] || reject "$ACTION: bad sock $(printf '%q' "$SOCK")"
fi
if [ -n "$CUR" ]; then
    valid_level "$CUR" || reject "$ACTION: bad cur $(printf '%q' "$CUR")"
fi
if [ -n "$TO" ]; then
    [[ $TO =~ ^[A-Za-z0-9_.:@-]+$ ]] || reject "$ACTION: bad session name $(printf '%q' "$TO")"
fi

case $ACTION in
    model | effort | ctx | diff) require_active_pane "$PANE" ;;
    *) ;;  # cost checks in send_slash, agent in agent_target; usage targets no pane
esac

# ── the status card (retro-hud://card): the creature's own popup ──
# One tip per ten minutes, generic on purpose; the card's facts come from
# the state file (`state_py card`). Any key closes it (a click cannot: tmux
# hands a popup no mouse unless it asks, and asking would let the opening
# right-click's release close it). `m` exits the popup with status 10,
# which display-popup -E hands back here, and the agent menu opens THEN:
# a menu asked for while a popup is up is silently dropped by tmux.
TIPS=(
    "right-click any HUD segment for its menu; q or Esc closes"
    "context gauge red near 80%? /compact before it fills"
    "settings.json refreshInterval 1: the creature moves each second"
    "RETRO_HUD_CREATURE=big or tall grows it; 0 is the text alien"
    "agent menu: quiet 1h mutes bubbles, wave makes it wave back"
    "RETRO_HUD_HOME_URL adds a ⌂ jump-home link to row 2"
    "/model and /effort: right-click the model name or effort dot"
    "the \$ field alternates with the session duration every 30 s"
)

vis_width() {  # longest display width of the lines on stdin (ANSI stripped)
    python3 -I -c '
import re, sys, unicodedata
w = 0
for line in sys.stdin.read().split("\n"):
    line = re.sub(r"\x1b\[[0-9;]*m", "", line)
    w = max(w, sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in line))
print(w)'
}

show_card() {  # pane; after agent_target
    local pane=$1 body tip file runner w h cols url
    if ! safe_path "$SELF" || ! safe_path "$LOG_DIR"; then
        log "card refused: unsafe handler or cache path; install them under plain paths"
        exit 0
    fi
    body=$(state_py card "$AGENT_NAME") || body="$AGENT_NAME · no status yet"
    tip=${TIPS[$(( $(date +%s) / 600 % ${#TIPS[@]} ))]}
    mkdir -p "$LOG_DIR" 2>/dev/null
    file=$(mktemp "$LOG_DIR/card.XXXXXX") && runner=$(mktemp "$LOG_DIR/card.XXXXXX.sh") || {
        log "card: cannot write under $LOG_DIR"; exit 0; }
    {
        printf '\033[1m%s\033[0m\n' "${body%%$'\n'*}"
        [ "$body" = "${body%%$'\n'*}" ] || printf '%s\n' "${body#*$'\n'}"
        printf '\n\033[2mtip: %s\033[0m\n' "$tip"
        printf '\033[2m%s\033[0m\n' "any key closes · m: menu"
    } >"$file"
    # printed without its final newline, so the cursor stays on the last line and the popup,
    # sized to the text, does not scroll its first line away ($(…) strips it; portable)
    { printf '#!/bin/bash\n'; popup_guard
      printf 'printf %%s "$(cat %s)"\n' "'$file'"; printf '%s' "$POPUP_READ"
      printf '[ "$k" = m ] && exit 10\nexit 0\n'; } >"$runner"
    w=$(( $(vis_width <"$file") + 4 ))
    h=$(( $(wc -l <"$file") + 2 ))
    read -r cols rows < <(tm display -p -c "$CLIENT" '#{client_width} #{client_height}' 2>/dev/null) || cols="" rows=""
    [[ ${cols:-} =~ ^[0-9]+$ ]] || cols=80
    [[ ${rows:-} =~ ^[0-9]+$ ]] || rows=24
    [ "$w" -le $((cols - 2)) ] || w=$((cols - 2))
    [ "$w" -ge 24 ] || w=24
    [ "$h" -le $((rows - 2)) ] || h=$((rows - 2))
    local rc=0
    tm display-popup -c "$CLIENT" -w "$w" -h "$h" -T " $AGENT_NAME " -E "bash '$runner'" || rc=$?
    rm -f "$file" "$runner"
    if [ "$rc" = 10 ]; then
        agent_menu "$pane"        # the popup is gone; now a menu can open (keyboard: no mouse event)
    elif [ "$rc" != 0 ]; then
        log "display-popup failed ($rc)"
    fi
}

# The speech cloud (a small dialogue box beside the creature, highlights only): inside the
# right-click binding the card is a small rounded popup at the pointer with
# the highlights only, written to the menu file like a menu so it carries the
# press's mouse event (-x M; -y the row below the box, so it stands ABOVE the
# creature). A click on the box or any key
# closes it; tmux hands a click outside a popup to nobody.
# m: the agent menu, c: the full card (centred), any other key closes. The
# runner removes its own files: the binding runs it after this script ends.
show_cloud() {  # pane; after agent_target
    local pane=$1 body head ctx file runner w h cols rows url
    if ! safe_path "$SELF" || ! safe_path "$LOG_DIR"; then
        log "cloud refused: unsafe handler or cache path; install them under plain paths"
        exit 0
    fi
    body=$(state_py card "$AGENT_NAME") || body="$AGENT_NAME · no status yet"
    head=${body%%$'\n'*}
    ctx=$(printf '%s\n' "$body" | grep -m1 '^context ' || true)
    mkdir -p "$LOG_DIR" 2>/dev/null
    file=$(mktemp "$LOG_DIR/cloud.XXXXXX") && runner=$(mktemp "$LOG_DIR/cloud.XXXXXX.sh") || {
        log "cloud: cannot write under $LOG_DIR"; exit 0; }
    {
        printf '\033[1m%s\033[0m\n' "$head"
        [ -z "$ctx" ] || printf '%s\n' "$ctx"
        printf '\033[2m%s\033[0m\n' "m menu · c card · click or key closes"
    } >"$file"
    url="retro-hud://card?pane=%25${pane#%}${SOCK:+&sock=$SOCK}"
    { printf '#!/bin/bash\n'; popup_guard
      printf 'printf %%s "$(cat %s)"\n' "'$file'"; printf '%s' "$POPUP_READ"
      printf 'rm -f %s %s\n' "'$file'" "'$runner'"; } >"$runner"
    # the popup must be gone before a menu or another popup may open: a short delay
    # no exec here: the EXIT trap (the popup marker) must still run
    printf '[ "$k" = m ] && tmux run-shell -b -d 0.3 %s\n' \
        "$(tmq "'$SELF' '${url/card?/agent?}'")" >>"$runner"
    printf '[ "$k" = c ] && tmux run-shell -b -d 0.3 %s\nexit 0\n' "$(tmq "'$SELF' '$url'")" >>"$runner"
    w=$(( $(vis_width <"$file") + 4 ))
    h=$(( $(wc -l <"$file") + 2 ))
    read -r cols rows < <(tm display -p -c "$CLIENT" '#{client_width} #{client_height}' 2>/dev/null) || cols="" rows=""
    [[ ${cols:-} =~ ^[0-9]+$ ]] || cols=80
    [[ ${rows:-} =~ ^[0-9]+$ ]] || rows=24
    [ "$w" -le $((cols - 2)) ] || w=$((cols - 2))
    [ "$h" -le $((rows - 2)) ] || h=$((rows - 2))
    printf "display-popup -c %s -x M -y '#{popup_mouse_y}' -w %s -h %s -b rounded -S fg=colour51 -T '' -E %s\n" \
        "$(tmq "$CLIENT")" "$w" "$h" "$(tmq "bash '$runner'")" >"$MENU_FILE.tmp" \
        && mv -f "$MENU_FILE.tmp" "$MENU_FILE" || { rm -f "$MENU_FILE.tmp" "$file" "$runner"; log "cloud: menu file write failed"; }
    log "cloud for $pane written to $MENU_FILE"
}

# ── sessions: every tmux session on this server with a pane running Claude ──
# What the HUD's presence cache knows about each (pane-<N>.sid -> <sid>.state.json)
# gives the state word and its age; a Claude pane the cache has not mapped shows as
# "unknown". One `list-panes -a` call; the clicking client's own session is marked.
# A local extension that keeps its own session list handles retro-hud://sessions
# before this runs and exits; this is the generic list others can build on.
SESSION_WORDS='
import json, os, re, sys, time
cache, me, remote = sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""
WORD = {"working": ("working", "#[fg=colour46]"), "yours": ("your turn", "#[fg=colour51]"),
        "needs": ("needs you", "#[fg=colour226,bold]"), "idle": ("idle", "#[dim]"),
        "asleep": ("asleep", "#[dim]"), "error": ("error", "#[fg=colour196]"),
        "paused": ("paused", "#[dim]")}
RANK = {"needs": 0, "yours": 1, "working": 2, "error": 3, "idle": 4, "asleep": 5, "paused": 6}
PART = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")   # a host or session name in a feed: no `:`
FRESH = 15 * 60
now = time.time()
seen = {}
for line in sys.stdin.read().split("\n"):
    f = line.split("\t")
    if len(f) < 4:
        continue
    name, pane, cmd, pid = f[0], f[1], f[2], f[3]
    runs = cmd == "claude"
    if not runs and pid.isdigit():  # a launcher in front: a direct child named claude
        try:
            for p in os.listdir("/proc"):
                if p.isdigit():
                    st = open("/proc/%s/stat" % p).read()
                    if st.split(") ")[-1].split()[1] == pid and "(claude)" in st:
                        runs = True
                        break
        except OSError:
            pass
    if not runs:
        continue
    state, since = None, None
    try:
        sid = open(os.path.join(cache, "pane-%s.sid" % pane.lstrip("%"))).read(256).strip()
        d = json.load(open(os.path.join(cache, sid + ".state.json")))
        state, since = d.get("state"), d.get("since")
    except (OSError, ValueError):
        pass
    if name in seen and state not in RANK:
        continue
    seen[name] = (state, since)
def row(name, state, since, current, remote=None):
    word, style = WORD.get(state, ("unknown", "#[dim]"))
    age = ""
    if isinstance(since, (int, float)) and now >= since:
        s = int(now - since)
        age = "%ds" % s if s < 60 else "%dm" % (s // 60) if s < 3600 else "%dh" % (s // 3600)
    r = {"name": name, "state": state if state in RANK else "unknown", "word": word,
         "style": style, "age": age, "current": current, "rank": RANK.get(state, 7)}
    if remote:
        r["remote"] = remote
        r["target"] = "remote:%s:%s" % (remote, name)
    return r
rows = [row(name, state, since, name == me) for name, (state, since) in seen.items()]
# the remote feed: <host>.json files written in the last FRESH seconds
try:
    feeds = sorted(os.listdir(remote)) if remote else []
except OSError:
    feeds = []
for fn in feeds:
    if not fn.endswith(".json"):
        continue
    path = os.path.join(remote, fn)
    try:
        if now - os.path.getmtime(path) > FRESH:
            continue
        d = json.load(open(path))
    except (OSError, ValueError):
        continue
    host = d.get("host") if isinstance(d, dict) else None
    host = host if isinstance(host, str) and PART.match(host) else fn[:-5]
    if not PART.match(host):
        continue
    names = set()
    for x in (d.get("sessions") if isinstance(d, dict) else None) or []:
        if not isinstance(x, dict):
            continue
        name = x.get("name")
        if not isinstance(name, str) or not PART.match(name) or name in names:
            continue
        names.add(name)
        rows.append(row(name, x.get("state"), x.get("since"), False, remote=host))
rows.sort(key=lambda r: (r["current"], r["rank"], r.get("remote", ""), r["name"]))
print(json.dumps(rows))
'

sessions_rows() {  # stdout: the JSON list (after need_client)
    local cache me remote
    cache=$(presence_cache) || cache=""
    me=$(tm display -p -c "$CLIENT" '#{session_name}' 2>/dev/null) || me=""
    remote=$(remote_dir) || remote=""
    tm list-panes -a -F $'#{session_name}\t#{pane_id}\t#{pane_current_command}\t#{pane_pid}' 2>/dev/null |
        python3 -I -c "$SESSION_WORDS" "$cache" "$me" "$remote"
}

switch_cmd() {  # a menu item that re-enters this script to switch to a session
    local url="retro-hud://switch?to=$1"
    [ -z "$SOCK" ] || url+="&sock=$SOCK"
    printf 'run-shell -b "RETRO_HUD_CLIENT=%s '"'"'%s'"'"' '"'"'%s'"'"'"' "$CLIENT" "$SELF" "$url"
}

show_sessions() {
    local rows items=() keys="asdfgwertzxcvb123456789" i=0 first="" n
    need_client
    rows=$(sessions_rows) || rows="[]"
    n=$(printf '%s' "$rows" | python3 -I -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null) || n=0
    first=$(printf '%s' "$rows" | python3 -I -c 'import json,sys
r = [x for x in json.load(sys.stdin) if x["state"] == "needs" and not x["current"]]
print((r[0].get("target") or r[0]["name"]) if r else "")' 2>/dev/null) || first=""
    if [ -n "$first" ]; then
        items+=("⇢  first that needs you: ${first#remote:}" n "$(switch_cmd "$first")")
    else
        items+=("-⇢  nobody needs you" "" "")
    fi
    while IFS=$'\x1f' read -r name word style age current target remote; do   # \x1f: an empty field stays a field
        [ -n "$name" ] || continue
        local text="${remote:+⌁ $remote:}$name   $style$word#[default]${age:+ $age}"
        if [ "$current" = 1 ]; then
            items+=("-$text · here" "" "")
        else
            items+=("$text" "${keys:$i:1}" "$(switch_cmd "${target:-$name}")")
            i=$((i + 1))
        fi
    done < <(printf '%s' "$rows" | python3 -I -c 'import json,sys
for x in json.load(sys.stdin):
    print("\x1f".join([x["name"], x["word"], x["style"], x["age"], "1" if x["current"] else "0",
                       x.get("target", ""), x.get("remote", "")]))' 2>/dev/null)
    [ "$n" -gt 0 ] || items+=("-no Claude session in tmux" "" "")
    show_menu " sessions ($n) " "${items[@]}"
}

# ⌂ and ↩ (RETRO_HUD_HOME_URL / RETRO_HUD_BACK_URL on the bar): home is the tmux
# session named by RETRO_HUD_HOME_SESSION (env or the config file; default "home").
# A ⌂ click records the session it came from in <cache>/home-from, which the bar
# reads to show ↩ on the home session; ↩ goes back there and clears the record.
home_from_file() {
    local d
    d=$(presence_cache) || return 1
    printf '%s/home-from' "$d"
}

home_session() { printf '%s' "${RETRO_HUD_HOME_SESSION:-${cfg_home_session:-home}}"; }

# Any arrival at home THROUGH this handler (⌂, the session list, needs, switch)
# records where it came from, so the ↩ on the home bar always means "the session
# I was in before I came here"; ↩ clears it. Arrivals tmux makes on its own are
# not seen, so the record can be stale: the bar ignores one older than 12 h.
note_arrival() {  # destination session; CLIENT set
    local home cur f
    home=$(home_session)
    [ "$1" = "$home" ] || return 0
    cur=$(tm display -p -c "$CLIENT" '#{session_name}' 2>/dev/null) || cur=""
    [ -n "$cur" ] && [ "$cur" != "$home" ] && [[ $cur =~ ^[A-Za-z0-9_.:@-]+$ ]] || return 0
    f=$(home_from_file) || return 0
    mkdir -p "$(dirname "$f")" 2>/dev/null
    printf '%s\n' "$cur" >"$f.tmp" && mv -f "$f.tmp" "$f" || log "home-from not written"
}

go_home() {
    local home cur
    home=$(home_session)
    need_client
    [[ $home =~ ^[A-Za-z0-9_.:@-]+$ ]] || reject "home: bad RETRO_HUD_HOME_SESSION $(printf '%q' "$home")"
    cur=$(tm display -p -c "$CLIENT" '#{session_name}' 2>/dev/null) || cur=""
    if [ "$cur" = "$home" ]; then
        tm display-message -c "$CLIENT" -d 1500 "retro-hud: already home" || true
        return 0
    fi
    switch_to "$home"
}

go_back() {
    local f from=""
    need_client
    if f=$(home_from_file) && [ -f "$f" ]; then
        from=$(head -c 256 "$f" | tr -d '\n')
        rm -f "$f"
    fi
    if [[ $from =~ ^[A-Za-z0-9_.:@-]+$ ]]; then
        switch_to "$from"
    else
        tm switch-client -c "$CLIENT" -l 2>/dev/null || go_home
    fi
}

# remote:<host>:<name> (a row from the remote feed): the feed file's `open`
# command ({host} and {name} filled in; default ssh + tmux attach) runs in a
# wrapper session here, rh-<host>-<name>, and the client goes there. A second
# click finds the wrapper and just switches; when the command ends (detach,
# a failed ssh) the wrapper closes and tmux puts the client elsewhere.
remote_open() {  # host name: the wrapper session's name on stdout, or nothing
    local host=$1 name=$2 d cmd w
    [[ $host =~ ^[A-Za-z0-9_.@-]{1,64}$ && $name =~ ^[A-Za-z0-9_.@-]{1,64}$ ]] || return 1
    d=$(remote_dir) || return 1
    cmd=$(python3 -I -c 'import json, sys
try:
    d = json.load(open(sys.argv[1]))
    c = d.get("open") if isinstance(d, dict) else None
    print(c if isinstance(c, str) and c.strip() and "\n" not in c else "")
except (OSError, ValueError):
    print("")' "$d/$host.json" 2>/dev/null) || cmd=""
    [ -n "$cmd" ] || cmd='ssh -t {host} tmux attach -t {name}'
    cmd=${cmd//\{host\}/$host}
    cmd=${cmd//\{name\}/$name}
    w="rh-$host-$name"
    w=${w//[^A-Za-z0-9_-]/_}
    if ! tm has-session -t "=$w" 2>/dev/null; then
        tm new-session -d -s "$w" "$cmd" 2>/dev/null || { log "switch: could not start $w"; return 1; }
    fi
    printf '%s' "$w"
}

switch_to() {  # session name, or remote:<host>:<name>: switch the clicking client there
    need_client
    if [[ $1 == remote:* ]]; then
        local rest=${1#remote:} w name=""
        [[ $rest == *:* ]] && name=${rest#*:}
        if w=$(remote_open "${rest%%:*}" "$name") && [ -n "$w" ]; then
            note_arrival "$w"
            tm switch-client -c "$CLIENT" -t "=$w" 2>/dev/null || log "switch: no wrapper $w"
        else
            log "switch: remote $1 refused"
            tm display-message -c "$CLIENT" -d 2500 "retro-hud: cannot open ${1#remote:}" || true
        fi
        return 0
    fi
    note_arrival "$1"
    tm switch-client -c "$CLIENT" -t "=$1" 2>/dev/null || {
        log "switch: no session $1"
        tm display-message -c "$CLIENT" -d 2500 "retro-hud: no tmux session $1" || true
    }
}

case $ACTION in
    usage)
        xdg-open "$USAGE_URL" >/dev/null 2>&1 || log "usage: xdg-open failed"
        ;;
    cost)
        send_slash "$PANE" cost
        ;;
    model)
        items=()
        i=0
        for m in "${MODELS[@]}"; do
            i=$((i + 1))
            key=""
            [ "$i" -gt 9 ] || key=$i
            items+=("$m" "$key" "$(menu_cmd send "$PANE" model "$m")")
        done
        items+=("pick… (Claude's own picker)" p "$(menu_cmd send "$PANE" model)")
        show_menu "/model $NOTE" "${items[@]}"
        ;;
    effort)
        items=()
        i=0
        for lvl in $LEVELS; do
            i=$((i + 1))
            label=$lvl
            [ "$lvl" != "$CUR" ] || label="$lvl  (current)"
            items+=("$label" "$i" "$(menu_cmd send "$PANE" effort "$lvl")")
        done
        show_menu "/effort $NOTE" "${items[@]}"
        ;;
    ctx)
        show_menu "context $NOTE" \
            "/compact" c "$(menu_cmd send "$PANE" compact)" \
            "/context" x "$(menu_cmd send "$PANE" context)" \
            "/clear…" l "$(menu_cmd confirm-clear "$PANE")"
        ;;
    diff)
        if [ -n "$MENU_FILE" ]; then   # inside the binding: the popup waits, the chain must not
            ( RETRO_HUD_MENU_FILE="" exec "$SELF" "$URL" ) </dev/null >/dev/null 2>&1 &
            exit 0
        fi
        dir=$(tm display -p -t "$PANE" '#{pane_current_path}' 2>/dev/null) || dir=""
        # a local extension may point the diff at another tree (a session whose work lives
        # elsewhere); it must still be an absolute, existing directory
        if [[ ${RETRO_HUD_DIFF_DIR:-} == /* && ${RETRO_HUD_DIFF_DIR:-} != *[[:cntrl:]]* ]] && [ -d "${RETRO_HUD_DIFF_DIR:-}" ]; then
            dir=$RETRO_HUD_DIFF_DIR
        fi
        if ! [[ $dir == /* && $dir != *[[:cntrl:]]* ]] || ! [ -d "$dir" ]; then
            log "diff: pane $PANE has no usable directory"
            exit 0
        fi
        # outside a repository `git diff` prints its --no-index usage page: say so instead,
        # long enough to read (display-message's default 750 ms is easy to miss)
        if ! GIT_CONFIG_NOSYSTEM=1 GIT_OPTIONAL_LOCKS=0 git -C "$dir" -c core.fsmonitor=false \
                rev-parse --is-inside-work-tree >/dev/null 2>&1; then
            log "diff: $dir is not in a git repository"
            tm display-message -c "$CLIENT" -d 4000 "retro-hud: no git repository in ${dir/#$HOME/\~}" || true
            exit 0
        fi
        # A fixed command string: the directory travels as -d, never as
        # shell text. The repo's own config must not run anything, so the
        # config-driven program hooks (fsmonitor, external diff, textconv,
        # pager) are switched off, and less runs in secure mode.
        git_base="GIT_CONFIG_NOSYSTEM=1 GIT_OPTIONAL_LOCKS=0 git -c core.fsmonitor=false"
        git_base+=" -c diff.external= -c core.pager= --no-pager"
        git_safe="$git_base diff --no-ext-diff --no-textconv --color=always --no-prefix"
        git_last="$git_base show --stat --patch --no-ext-diff --no-textconv --color=always --no-prefix HEAD"
        # the pager's text: a summary line, the file list, then hunks; git's plumbing lines
        # (diff --git, index …) are dropped, file headers read --- app.py / +++ app.py
        tidy="sed -E '/^(\\x1b\\[[0-9;]*m)*(diff --git|index )/d'"
        guard=""
        [ -z "$POPUP_MARK" ] || guard="touch $(tmq "$POPUP_MARK"); trap $(tmq "rm -f '$POPUP_MARK'") EXIT; "
        # A clean tree shows the last commit instead of a blank pager. q closes, the wheel
        # scrolls (--mouse). No Esc binding:
        # with the mouse on, every wheel report starts with Esc and would quit the pager.
        body="d=\$($git_safe 2>&1); if [ -z \"\$d\" ]; then printf '\\033[1mworking tree clean\\033[0m · the last commit\\n\\n'; $git_last | $tidy; else printf '\\033[1muncommitted changes\\033[0m · %s\\n\\n' \"\$($git_safe --shortstat | sed 's/^ *//')\"; $git_safe --stat | sed '\$d'; echo; printf '%s\\n' \"\$d\" | $tidy; fi"
        tm display-popup -c "$CLIENT" -d "$dir" -w 90% -h 90% -T " git diff (read-only) · q closes " -E \
            "$guard{ $body; } 2>&1 | LESSSECURE=1 less -R --mouse -P' q closes · wheel scrolls '" ||
            log "display-popup failed"
        ;;
    # ── agent action: BEGIN ──
    agent)
        agent_target "$PANE"
        agent_menu "$PANE"
        ;;
    sessions)
        show_sessions
        ;;
    needs)
        need_client
        first=$(sessions_rows | python3 -I -c 'import json,sys
r = [x for x in json.load(sys.stdin) if x["state"] == "needs" and not x["current"]]
print((r[0].get("target") or r[0]["name"]) if r else "")' 2>/dev/null) || first=""
        if [ -n "$first" ]; then
            switch_to "$first"
        else
            tm display-message -c "$CLIENT" -d 2500 "retro-hud: nobody needs you right now" || true
        fi
        ;;
    switch)
        [ -n "$TO" ] || reject "switch: no session named (to=)"
        switch_to "$TO"
        ;;
    home)
        go_home
        ;;
    back)
        go_back
        ;;
    card)
        agent_target "$PANE"
        if [ -n "$MENU_FILE" ]; then   # inside the binding: the speech cloud at the pointer
            show_cloud "$PANE"
        else
            show_card "$PANE"          # the full card, centred (the cloud's c, or a desktop click)
        fi
        ;;
    # ── agent action: END ──
esac
exit 0
