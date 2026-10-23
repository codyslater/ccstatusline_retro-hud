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
#
# Settings come from the environment or, because a desktop-launched
# handler never reads your shell rc files, from ~/.config/retro-hud/env:
# plain KEY=VALUE lines, read line by line (never sourced). Keys:
#   RETRO_HUD_MODELS      comma list for the model menu (opus,sonnet,haiku)
#   RETRO_HUD_USAGE_URL   page the rate-limit gauges open
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
cfg_models="" cfg_usage_url=""
if [ -f "$CONFIG" ]; then
    n=0
    while IFS= read -r line || [ -n "$line" ]; do
        n=$((n + 1))
        [[ $line =~ ^[[:space:]]*(#|$) ]] && continue
        if [[ $line =~ ^(RETRO_HUD_MODELS|RETRO_HUD_USAGE_URL)=(.*)$ ]]; then
            key=${BASH_REMATCH[1]} val=${BASH_REMATCH[2]}
            if [[ $val =~ ^\"(.*)\"$ || $val =~ ^\'(.*)\'$ ]]; then
                val=${BASH_REMATCH[1]}
            fi
            case $key in
                RETRO_HUD_MODELS) cfg_models=$val ;;
                RETRO_HUD_USAGE_URL) cfg_usage_url=$val ;;
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
    need_client
    tm display-menu -c "$CLIENT" -x C -y C -T "$title" "$@" || log "display-menu failed"
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

case $ACTION in usage | agent) need_pane=0 ;; *) need_pane=1 ;; esac
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
    *) ;;  # cost checks in send_slash; usage and agent target no pane
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
    # ── agent action: BEGIN (reserved; its menu arrives in a later release) ──
    agent)
        log "agent: reserved for a later release"
        ;;
    # ── agent action: END ──
esac
exit 0
