#!/usr/bin/env bash
# retro-hud reference handler for retro-hud:// click actions.
#
# Your desktop runs this with ONE argument, the clicked URL:
#
#   retro-hud://<action>?pane=<tmux pane id>[&sock=<tmux socket>]
#
# actions: model effort ctx cost diff usage agent (see README, "Click
# actions"). The URL is checked against a strict whitelist and every query
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

if [ -f "$LOCAL_EXT" ]; then
    # It sees "$@"; returning (with any status) falls through to the
    # built-in actions, `exit` ends the click.
    # shellcheck source=/dev/null
    . "$LOCAL_EXT" "$@" || true
fi

# ── settings: environment first, then the config file, then defaults ──
cfg_models="" cfg_usage_url="" cfg_agent_name="" cfg_cache_dir=""
if [ -f "$CONFIG" ]; then
    n=0
    while IFS= read -r line || [ -n "$line" ]; do
        n=$((n + 1))
        [[ $line =~ ^[[:space:]]*(#|$) ]] && continue
        if [[ $line =~ ^(RETRO_HUD_MODELS|RETRO_HUD_USAGE_URL|RETRO_HUD_AGENT_NAME|RETRO_HUD_CACHE_DIR)=(.*)$ ]]; then
            key=${BASH_REMATCH[1]} val=${BASH_REMATCH[2]}
            if [[ $val =~ ^\"(.*)\"$ || $val =~ ^\'(.*)\'$ ]]; then
                val=${BASH_REMATCH[1]}
            fi
            case $key in
                RETRO_HUD_MODELS) cfg_models=$val ;;
                RETRO_HUD_USAGE_URL) cfg_usage_url=$val ;;
                RETRO_HUD_AGENT_NAME) cfg_agent_name=$val ;;
                RETRO_HUD_CACHE_DIR) cfg_cache_dir=$val ;;
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

# The handler has no $TMUX: the clicking client is the attached client
# with the newest activity.
newest_client() {
    tm list-clients -F '#{client_activity} #{client_tty}' 2>/dev/null |
        sort -rn | head -n 1 | cut -d' ' -f2-
}

need_client() {
    CLIENT=$(newest_client) || CLIENT=""
    if [ -z "$CLIENT" ]; then
        log "no tmux client found (is the tmux server running?)"
        exit 0
    fi
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
    # -O: keep the menu open when the mouse button is RELEASED outside it. A menu opened by a
    # right-click press (tmux's mouse_hyperlink binding) would otherwise be dismissed by the
    # matching release a few ms later. A later press outside, Esc or q still closes it.
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

send_slash() {  # pane, command, [arg]
    local pane=$1 text current
    shift
    text=$(slash_text "$@") || reject "send: $(printf '%q ' "$@")"
    require_active_pane "$pane"
    current=$(tm display -p -t "$pane" '#{pane_current_command}' 2>/dev/null) || current=""
    if [ "$current" != "claude" ]; then
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
# Claude: the state file (<sid>.state.json, keys mute_until, sprite and
# seed; the HUD's `creature` key says the pixel creature is on)
# and the events channel (<sid>.events.jsonl). The HUD records which
# session a pane shows in <cache>/pane-<N>.sid (pane %N) while click
# actions are on, so the session is found from the pane, never the URL.
SPRITE_SETS="alien cat robot ghost"
FAMILIES="blob beast alien bot"  # the pixel creature's families
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
    current=$(tm display -p -t "$pane" '#{pane_current_command}' 2>/dev/null) || current=""
    if [ "$current" != "claude" ]; then
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
    local pane=$1 extra=()
    if creature_on; then extra=("reroll" r "$(menu_cmd agent "$pane" reroll)"); fi
    show_menu "$AGENT_NAME" \
        "wave" w "$(menu_cmd agent "$pane" wave)" \
        "quiet 1h" q "$(menu_cmd agent "$pane" quiet)" \
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
                wave:1 | quiet:1 | sprites:1 | reroll:1 | status:1) ;;
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
re='^retro-hud://(model|effort|ctx|cost|diff|usage|agent)(\?([A-Za-z0-9_=&%.:/~+-]*))?$'
[[ $URL =~ $re ]] || reject "$(printf '%q' "$URL")"
ACTION=${BASH_REMATCH[1]}
QUERY=${BASH_REMATCH[3]}
[[ $QUERY != *%00* ]] || reject "NUL in query"

urldecode() {  # the trailing x keeps decoded trailing newlines visible
    local s=${1//%/\\x}
    printf '%b' "$s"
    printf x
}

PANE="" CUR="" has_sock=0
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
        # unknown keys (including a `cwd`) are ignored, so the contract can
        # grow; directories always come from tmux, never from a link
        *) ;;
    esac
done

case $ACTION in usage) need_pane=0 ;; *) need_pane=1 ;; esac
if [ "$need_pane" = 1 ] || [ -n "$PANE" ]; then
    [[ $PANE =~ ^%[0-9]+$ ]] || reject "$ACTION: bad pane $(printf '%q' "$PANE")"
fi
if [ "$has_sock" = 1 ]; then
    safe_path "$SOCK" && [ -S "$SOCK" ] || reject "$ACTION: bad sock $(printf '%q' "$SOCK")"
fi
if [ -n "$CUR" ]; then
    valid_level "$CUR" || reject "$ACTION: bad cur $(printf '%q' "$CUR")"
fi

case $ACTION in
    model | effort | ctx | diff) require_active_pane "$PANE" ;;
    *) ;;  # cost checks in send_slash, agent in agent_target; usage targets no pane
esac

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
        dir=$(tm display -p -t "$PANE" '#{pane_current_path}' 2>/dev/null) || dir=""
        if ! [[ $dir == /* && $dir != *[[:cntrl:]]* ]] || ! [ -d "$dir" ]; then
            log "diff: pane $PANE has no usable directory"
            exit 0
        fi
        # A fixed command string: the directory travels as -d, never as
        # shell text. The repo's own config must not run anything, so the
        # config-driven program hooks (fsmonitor, external diff, textconv,
        # pager) are switched off, and less runs in secure mode.
        git_safe="GIT_CONFIG_NOSYSTEM=1 GIT_OPTIONAL_LOCKS=0 git -c core.fsmonitor=false"
        git_safe+=" -c diff.external= -c core.pager= --no-pager diff --no-ext-diff --no-textconv"
        tm display-popup -c "$CLIENT" -d "$dir" -w 90% -h 90% -T " git diff (read-only) " -E \
            "{ $git_safe --stat --color=always; echo; $git_safe --color=always; } 2>&1 | LESSSECURE=1 less -R" ||
            log "display-popup failed"
        ;;
    # ── agent action: BEGIN ──
    agent)
        agent_target "$PANE"
        agent_menu "$PANE"
        ;;
    # ── agent action: END ──
esac
exit 0
