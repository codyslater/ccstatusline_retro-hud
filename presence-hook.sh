#!/usr/bin/env bash
# retro-hud agent presence hook for Claude Code (installed by
# `install.sh --hooks`; no dependencies beyond bash).
#
# Appends one JSON line to <cache>/<session_id>.hooks.jsonl:
#     {"ts": <epoch seconds>, "state": "<state>"[, "src": "<source>"]}
# so the status line can tell what the transcript alone cannot — above
# all, that a permission prompt is waiting for you. <cache> is
# $RETRO_HUD_CACHE_DIR, else ~/.cache/retro-hud, else /tmp/retro-hud-<uid>.
#
# Usage (the hook's JSON arrives on stdin):
#     presence-hook.sh yours               # Stop
#     presence-hook.sh working             # UserPromptSubmit
#     presence-hook.sh needs               # Notification, permission_prompt
#     presence-hook.sh yours idle_prompt   # Notification, idle_prompt
# Without arguments the state is derived from hook_event_name (and
# notification_type) in the stdin JSON.
#
# A hook must never get in the way: anything a UserPromptSubmit hook
# prints is added to the conversation, and a failing Stop hook can hold
# the agent up. So: no output, no `set -e`, and exit 0 whatever happens.

input=""
IFS= read -r -d '' input 2>/dev/null

field() {  # field NAME → $REPLY = the first "NAME": "value" (escaped quotes never match)
    local re="\"$1\"[[:space:]]*:[[:space:]]*\"([^\"]*)\""
    REPLY=""
    if [[ $input =~ $re ]]; then REPLY=${BASH_REMATCH[1]}; fi
}

field session_id
sid=$REPLY
[[ $sid =~ ^[A-Za-z0-9_-]{1,128}$ ]] || exit 0

state=${1:-}
src=${2:-}
if [[ -z $state ]]; then
    field hook_event_name
    case $REPLY in
        Stop) state=yours ;;
        UserPromptSubmit) state=working ;;
        Notification)
            field notification_type
            case $REPLY in
                permission_prompt) state=needs ;;
                idle_prompt) state=yours; src=idle_prompt ;;
            esac ;;
    esac
fi
case $state in working|yours|needs) ;; *) exit 0 ;; esac
[[ $src =~ ^[A-Za-z_]{0,32}$ ]] || src=""

dir=${RETRO_HUD_CACHE_DIR:-}
if [[ -n $dir ]]; then
    mkdir -p -m 700 "$dir" 2>/dev/null || exit 0
elif [[ -n ${HOME:-} ]] && mkdir -p -m 700 "$HOME/.cache/retro-hud" 2>/dev/null; then
    dir="$HOME/.cache/retro-hud"
else
    dir="/tmp/retro-hud-${UID}"
    mkdir -p -m 700 "$dir" 2>/dev/null || exit 0
    [[ -O $dir ]] || exit 0
fi

ts=${EPOCHREALTIME:-}
ts=${ts/,/.}  # some locales use a decimal comma
if ! [[ $ts =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
    printf -v ts '%(%s)T' -1 2>/dev/null
    [[ $ts =~ ^[0-9]+$ ]] || ts=$(date +%s 2>/dev/null)
    [[ $ts =~ ^[0-9]+$ ]] || exit 0
fi

line="{\"ts\": $ts, \"state\": \"$state\""
[[ -n $src ]] && line+=", \"src\": \"$src\""
printf '%s}\n' "$line" >> "$dir/$sid.hooks.jsonl" 2>/dev/null
exit 0
