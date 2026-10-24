#!/usr/bin/env python3
"""Claude Code statusLine — RETRO SCI-FI HUD

Two-row HUD with a full wireframe, zoned gauges, width-aware
degradation and a living pixel creature on the frame. Reads the
statusline JSON payload on stdin and prints two ANSI lines sized to
$COLUMNS (three with RETRO_HUD_CREATURE=tall).

Flags:
    --version   print version and exit
    --demo      render with sample data (no stdin needed)

Env toggles:
    RETRO_HUD_FRAME=0            disable the right-edge frame fill
    RETRO_HUD_COUNTDOWN_PCT=70   rate-limit % at which the label pins both the
                                 % and the reset countdown (default: the amber
                                 zone, so pinning starts when the gauge warns)
    RETRO_HUD_COST_MODE=cycle    cycle: duration and cost share ONE field,
                                 alternating every 30s, padded to the wider
                                 label so the flip moves nothing; both: two
                                 segments (T:… and $…) as before
    RETRO_HUD_RL_MODE=cycle      rate-limit labels below the pin threshold:
                                 cycle (alternate % and time-to-reset every
                                 30s, every 10s in the red zone), pct, time,
                                 or both
    RETRO_HUD_ALIEN=0            ground the creature (or alien) that walks
                                 the top rule (a tall head line stays, blank)
    RETRO_HUD_CTX_TOKENS=auto    context token readout: auto (amber zone up),
                                 always, or never
    RETRO_HUD_MARGIN=4           columns kept free at the right edge (raise if
                                 your terminal truncates lines with an ellipsis)
    RETRO_HUD_WIDTH=<cols>       hard width override when $COLUMNS lies
    RETRO_HUD_EMOJI=2            2: emoji are two cells (normal); 1: count them
                                 as one cell (some WSL/VS Code terminals);
                                 0: skip the folder emoji entirely
    RETRO_HUD_HOME_URL=<url>     end row 2 with a ⌂ jump-home link (OSC 8) to
                                 any URL your desktop can open; never dropped
    RETRO_HUD_ACTIONS=1          click actions: model, effort, context, cost
                                 (or a list: model,diff,agent,card links
                                 only those; ctx, cost, usage stay plain)
                                 and lines become retro-hud:// links (inside
                                 tmux only); the rate-limit gauges link to
                                 retro-hud://usage everywhere. Needs a
                                 handler for the scheme (install.sh --handler)
    RETRO_HUD_PRESENCE=0         gauge-only creature: ignore what the agent does
    RETRO_HUD_CREATURE=tiny      the creature's size: tiny (braille dots on
                                 the top rule), big (half blocks straddling
                                 rows 1 and 2), tall (half blocks with a
                                 head line: three lines), or 0 for the 2.x
                                 HUD with the text-art alien. The state
                                 file's `size` wins, except over 0
    RETRO_HUD_TICK_S=1           seconds per creature frame (pair with
                                 statusLine.refreshInterval 1 to see it move
                                 every second)
    RETRO_HUD_EXCURSIONS=0       keep the creature on its rule: no trips
                                 over the rest of the bar (tiny and big)
    RETRO_HUD_CREATURE_SEED=<s>  pin the creature's look (integer or any
                                 string; default: the session id)
    RETRO_HUD_CREATURE_COLOR=<c> pin its colour: pink, green, purple, cyan,
                                 orange, a 256-colour index, or mood (its
                                 own seeded colour, turning yellow when it
                                 needs you, pink on error, dim idle/asleep)
    RETRO_HUD_SPRITE=alien       creature family: blob, beast, alien, bot (the
                                 2.x names cat, robot, ghost map to beast,
                                 bot, blob); with the creature off, the
                                 text-art set: alien, cat, robot, ghost
    RETRO_HUD_SESSION_NAME=1     the ◈ session-name segment: 1, icon (◈ only), 0
    RETRO_HUD_AGENT_NAME=<name>  prefix state bubbles ("Nova: ready")
    RETRO_HUD_BUBBLES=alerts     what the creature may say: alerts (default) =
                                 only "need you" / "compact?" / "limit soon"
                                 plus events-channel messages; all = also the
                                 narration ("ready", "hm.", z/zZ, idle quips);
                                 off = nothing, events included
    RETRO_HUD_QUIPS=0            no idle quips (only matters with BUBBLES=all)
    RETRO_HUD_IDLE_MIN=10        minutes of "your turn" before idle
    RETRO_HUD_SLEEP_MIN=60       minutes of "your turn" before asleep
    RETRO_HUD_CACHE_DIR=<dir>    presence files (default ~/.cache/retro-hud)

Agent presence: the creature on the top rule (a seeded pixel monster in
braille or half blocks that wanders, blinks, breathes and hops on its own,
frame = now // RETRO_HUD_TICK_S) follows the session's agent,
read from a bounded tail of the transcript (entry type, stop reason,
error flag and timestamp only; never message text) and, when
`install.sh --hooks` was run, from presence-hook.sh's log. It hustles
while the agent works, waves when the turn is yours, beckons at a
permission prompt, flinches at a burst of tool errors, then dozes and
sleeps; a red- or amber-zone gauge still takes precedence. Short bubbles
beside it come from the events channel
(<cache>/<session_id>.events.jsonl, one {"ts", "text", "ttl", "icon"}
per line; "icon" is one character the creature holds up), from state
changes, and from rare idle quips; an event whose text is "wave" makes it
wave instead. With RETRO_HUD_ACTIONS=1 in tmux the creature links to
retro-hud://card (a status card for the session) and the session-name
segment (◈ name) to retro-hud://agent (wave, quiet, sprite, size, reroll,
status);
the state file also carries the card's facts (model, effort, dur_s,
lines_add, lines_del, dir).

Rate-limit label escalation: while a gauge is calm its label cycles (or
is pinned by RETRO_HUD_RL_MODE); the moment it reaches the amber zone it
stops rotating for good and pins both numbers — "20h30m · 77%" on the
five-hour side, "77% · 20h30m" on the seven-day side, mirrored so that
the % is always the token touching its own bar. Each gauge escalates on
its own, and the pinned label is the last thing row 2 gives up when the
terminal narrows, so neither number flickers away under you.
"""
__version__ = "3.1.1"

import calendar
import json
import os
import re
import shutil
import sys
import time
import unicodedata
import zlib
from urllib.parse import quote

# ── HIGH CONTRAST sci-fi palette ──
R = "\033[0m"

MODEL_BOX = "\033[1;38;5;46m"
MODEL_TXT = "\033[1;38;5;231m"
BRANCH_BADGE = "\033[1;97;48;5;129m"

NEON_CYAN = "\033[1;38;5;51m"
NEON_GREEN = "\033[1;38;5;46m"
NEON_YEL = "\033[1;38;5;226m"
NEON_RED = "\033[1;38;5;196m"
NEON_PINK = "\033[1;38;5;198m"
NEON_WHT = "\033[1;38;5;231m"
NEON_ORG = "\033[1;38;5;208m"
DIM = "\033[38;5;240m"
RULE = "\033[38;5;28m"  # dim green frame rule

# rate-limit gauge palettes (5h blue / 7d violet)
RL_5H_FC = "\033[1;38;5;33m"
RL_5H_EC = "\033[38;5;17m"
RL_7D_FC = "\033[1;38;5;135m"
RL_7D_EC = "\033[38;5;54m"

# context gauge zone tints (empty-cell backgrounds: green / amber / red zones)
ZONE_EC = ("\033[38;5;22m", "\033[38;5;58m", "\033[38;5;52m")
WARN_PCT = 70   # amber zone starts
RED_PCT = 90    # red zone starts

# rate-limit label cycle periods (seconds); the red zone flips faster so
# urgency reads as tempo — 10s is the floor the 5s refresh can show cleanly
CYCLE_S = 30
RED_CYCLE_S = 10

SEP = " " + NEON_CYAN + "//" + R + " "

_FULL = "█"
_FRAC = ["", "▏", "▎", "▍", "▌", "▋", "▊", "▉"]

EFFORT_GLYPHS = {"low": "·", "medium": "•", "high": "●",
                 "xhigh": "◉", "max": "✦"}
EFFORT_COLORS = {"low": DIM, "medium": NEON_CYAN, "high": NEON_YEL,
                 "xhigh": NEON_ORG, "max": NEON_PINK}
PR_STATE = {"approved": (NEON_GREEN, "✓"), "pending": (NEON_YEL, "○"),
            "changes_requested": (NEON_RED, "✗"), "draft": (DIM, "◌")}
# ASCII text-art alien: two blink frames per mood, all width-5 so the
# frame math never shifts. Calm cruises, agitated bares fangs, red-zone
# throws its arms up.
ALIEN_FRAMES = (("/o.o\\", "/-.-\\"),
                (">o.o<", ">-.-<"),
                ("\\o.o/", "\\O.O/"))
ALIEN_SPEEDS = (1, 2, 4)  # rule-cells per 30s tick

# Agent presence: one sprite per mood, two frames each, all width 5. The
# gauge moods (calm / agitated / red) of the alien are ALIEN_FRAMES; the
# rest follow what the session's agent is doing. Every mood's first frame
# is unique within its set, so a glance tells them apart.
SPRITES = {
    "alien": {
        "calm": ALIEN_FRAMES[0], "agitated": ALIEN_FRAMES[1], "red": ALIEN_FRAMES[2],
        "error": ("/>.<\\", "\\>.</"),     # flinches
        "working": ("/o.o/", "\\o.o\\"),   # hustles
        "yours": ("\\^.^/", "/^.^\\"),     # waves: your turn
        "needs": ("/o.o?", "\\o.o?"),      # beckons: a prompt is waiting
        "idle": ("/-_-\\", "/-_-\\"),      # dozes
        "asleep": ("/_._\\", "/_._\\"),
    },
    "cat": {
        "calm": ("=^.^=", "=-.-="), "agitated": (">^.^<", ">-.-<"),
        "red": ("\\^O^/", "/^O^\\"), "error": ("=>.<=", "=x.x="),
        "working": ("=^.^/", "\\^.^="), "yours": ("\\^w^/", "=^w^="),
        "needs": ("=^.^?", "=^o^?"), "idle": ("=-_-=", "=-_-="),
        "asleep": ("=_._=", "=_._="),
    },
    "robot": {
        "calm": ("[o_o]", "[-_-]"), "agitated": ("{o_o}", "{-_-}"),
        "red": ("\\[O]/", "/[O]\\"), "error": ("[x_x]", "[X_X]"),
        "working": ("[o_o>", "<o_o]"), "yours": ("[^_^]", "[^_^/"),
        "needs": ("[o_o?", "[?_?]"), "idle": ("[=_=]", "[=_=]"),
        "asleep": ("[_._]", "[_._]"),
    },
    "ghost": {
        "calm": ("(o.o)", "(-.-)"), "agitated": ("(O.O)", "(o.O)"),
        "red": ("\\(O)/", "/(O)\\"), "error": ("(x.x)", "(>.<)"),
        "working": ("(o.o~", "~o.o)"), "yours": ("(^.^)", "(^.^/"),
        "needs": ("(o.o?", "(?.?)"), "idle": ("(-_-)", "(-_-)"),
        "asleep": ("(_._)", "(_._)"),
    },
}
# rule-cells per 10s tick; 0 parks the sprite where it was when the mood began
MOOD_SPEEDS = {"calm": 1, "agitated": 2, "red": 4, "error": 2, "working": 3,
               "yours": 1, "needs": 0, "idle": 0, "asleep": 0}
WAVE_S = 30  # "yours" waves in place this long before cruising again
MOOD_COLORS = {"calm": NEON_GREEN, "agitated": NEON_ORG, "red": NEON_RED,
               "error": NEON_PINK, "working": NEON_CYAN, "yours": NEON_GREEN,
               "needs": NEON_YEL, "idle": "\033[38;5;65m", "asleep": DIM}
BUBBLE = "\033[38;5;245m"  # dim speech-bubble text on the rule
BUBBLE_MAX = 18            # visible chars of bubble text

# How many cells the terminal advances for emoji (EAW Wide/Fullwidth).
# Correct terminals use 2; some WSL/VS Code setups advance only 1 —
# RETRO_HUD_EMOJI=1 makes our accounting match them.
_EMOJI_W = 2
VIM_COLORS = {"NORMAL": NEON_CYAN, "INSERT": NEON_GREEN,
              "VISUAL": NEON_PINK, "VISUAL LINE": NEON_PINK}

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m|\x1b\]8;;[^\x07\x1b]*(?:\x07|\x1b\\)")


# ── helpers ──
def strip_ansi(s):
    return _ANSI_RE.sub("", s)


def vwidth(s):
    """Visible width accounting for double-width chars (emoji, CJK)."""
    w = 0
    for ch in s:
        w += _EMOJI_W if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def vislen(s):
    return vwidth(strip_ansi(s))


def fmt_short_dur(ms):
    """Session duration, rounded hard, so the duration ↔ cost field barely
    changes width as it flips: whole hours from 1h (1h30m → 2h), else
    minutes to the nearest 5 (47m → 45m), else "0m"."""
    mins = int(ms) // 60000
    m5 = int(5 * round(mins / 5.0)) if mins >= 5 else mins
    if m5 >= 60:
        return "{}h".format(max(1, int(round(mins / 60.0))))
    return "{}m".format(m5)


def fmt_short_cost(cost):
    """Cost to two significant figures: $0.4, $5.4, $21, $210, $1.2k."""
    c = float(cost)
    if c < 10:
        return "${:.1f}".format(c)
    if c < 100:
        return "${:.0f}".format(c)
    if c < 1000:
        return "${:.0f}".format(10 * round(c / 10.0))
    return "${:.1f}k".format(c / 1000.0)


def trunc(s, maxw):
    """Truncate to maxw visible columns, '..' suffix when cut."""
    if vwidth(s) <= maxw:
        return s
    if maxw <= 2:
        return s[:maxw]
    out, w = "", 0
    for ch in s:
        cw = vwidth(ch)
        if w + cw > maxw - 2:
            break
        out += ch
        w += cw
    return out + ".."


# ── cell compositor: lay creature cells over a rendered row ──
_CORNERS = frozenset("┌┐└┘")


def split_cells(s):
    """(cells, tail): `s` as its visible cells, each [escapes before it,
    its character]. A wide character is followed by ["", ""], the second
    cell it owns; `tail` is the escapes after the last cell. Joining them
    back (join_cells) gives `s` byte for byte."""
    cells, esc, at = [], "", 0
    for m in list(_ANSI_RE.finditer(s)) + [None]:
        for ch in s[at:m.start() if m else len(s)]:
            cells.append([esc, ch])
            esc = ""
            if vwidth(ch) == 2:
                cells.append(["", ""])
        if m:
            esc += m.group(0)
            at = m.end()
    return cells, esc


def join_cells(cells, tail=""):
    return "".join(e + t for e, t in cells) + tail


def _sgr_after(state, esc):
    """The SGR codes in force after `esc`: set codes add up, a reset
    clears them (the HUD never uses partial resets)."""
    for m in re.finditer(r"\x1b\[([0-9;]*)m", esc):
        p = m.group(1)
        state = "" if p in ("", "0") else (m.group(0) if p.startswith("0;") else state + m.group(0))
    return state


def overlay(row, col, items):
    """`row` with `items` (one-cell strings, None = see-through) laid over
    its cells from `col` on. Only cell text is replaced: every escape of
    the row stays where it was, so a colour or a link that spans the
    covered cells keeps its open and close, and the colour in force is set
    again after each covered run. A wide character half covered is
    replaced whole (its other half becomes a space). The frame corners and
    the cell after a leading corner (the ┌─ / └─ leads) are never covered.
    The visible width is unchanged."""
    cells, tail = split_cells(row)
    n = len(cells)
    keep = {i for i in range(n) if cells[i][1] in _CORNERS}
    if n > 1 and cells[0][1] in ("┌", "└"):
        keep.add(1)
    put = {}
    for k, item in enumerate(items):
        i = col + k
        if item is not None and 0 <= i < n and i not in keep:
            put[i] = item
    for i in list(put):
        if cells[i][1] == "" and i - 1 not in put:      # second half only
            put[i - 1] = " "
        elif i + 1 < n and cells[i + 1][1] == "" and cells[i][1] and i + 1 not in put:
            put[i + 1] = " "                             # first half only
    out, state = [], ""
    for i, (esc, ch) in enumerate(cells):
        state = _sgr_after(state, esc)
        if i in put:
            out.append(esc + R + put[i] + R)
            if i + 1 not in put and state:
                out.append(state)
        else:
            out.append(esc + ch)
    return "".join(out) + tail


def clamp(n, lo, hi):
    return max(lo, min(n, hi))


def fmt_tok(n):
    if n >= 1_000_000:
        return "{:.1f}M".format(n / 1_000_000)
    if n >= 1_000:
        return "{:.1f}K".format(n / 1_000)
    return str(n)


def fmt_win(n):
    if n >= 1_000_000:
        return "{:g}M".format(n / 1_000_000)
    if n >= 1_000:
        return "{}K".format(n // 1_000)
    return str(n)


def fmt_countdown(secs):
    if secs <= 0:
        return "0m"
    if secs >= 86400:
        d, rem = divmod(secs, 86400)
        h = rem // 3600
        return "{}d{}h".format(d, h) if h else "{}d".format(d)
    if secs >= 3600:
        h, rem = divmod(secs, 3600)
        m = rem // 60
        return "{}h{:02d}m".format(h, m) if m else "{}h".format(h)
    return "{}m".format(max(secs // 60, 1))


def link(url, text):
    if url:
        return "\033]8;;{}\a{}\033]8;;\a".format(url, text)
    return text


# ── click actions (RETRO_HUD_ACTIONS=1) ──
_PANE_RE = re.compile(r"%[0-9]+\Z")


def action_query():
    """Query for retro-hud://<action> links: the tmux pane and its server's
    socket. No directory: the handler asks tmux for the pane's own path,
    so a link printed by anything else cannot point git elsewhere.

    Empty when $TMUX_PANE is missing or malformed — we are not inside
    tmux, so nothing can be typed into this session.
    """
    pane = os.environ.get("TMUX_PANE", "")
    if not _PANE_RE.match(pane):
        return ""
    q = "pane=" + quote(pane, safe="")
    sock = os.environ.get("TMUX", "").split(",")[0]
    if sock:
        q += "&sock=" + quote(sock, safe="/")
    return q


_ACTION_NAMES = ("model", "effort", "ctx", "cost", "diff", "usage", "agent", "card", "sessions")


def actions_on():
    """RETRO_HUD_ACTIONS: True for "1" (every action links), a set of the
    named actions for a comma list (only the segments you want clickable),
    else None (off). Unknown names are dropped; a
    list with no known name is off."""
    v = os.environ.get("RETRO_HUD_ACTIONS", "").strip()
    if v == "1":
        return True
    names = {n.strip() for n in v.split(",")} & set(_ACTION_NAMES)
    return names or None


def make_action():
    """Return action(name, text, extra="") for this render.

    Off (the default) it returns text untouched, so the output is
    byte-identical to a HUD without click actions. On, `usage` always
    links (it only opens a web page); every other action links only
    inside tmux.
    """
    allowed = actions_on()
    if not allowed:
        return lambda name, text, extra="": text
    query = action_query()

    def action(name, text, extra=""):
        if allowed is not True and name not in allowed:
            return text  # a segment left plain by the RETRO_HUD_ACTIONS list
        if name == "usage":
            return link("retro-hud://usage" + ("?" + query if query else ""), text)
        if not query:
            return text
        return link("retro-hud://{}?{}{}".format(name, query, extra), text)
    return action


# ── git via file reads (no subprocess, no PATH dependency) ──
def _find_gitdir(cwd):
    d = cwd
    while True:
        g = os.path.join(d, ".git")
        if os.path.isdir(g):
            return g
        if os.path.isfile(g):  # worktree / submodule pointer
            try:
                with open(g) as f:
                    first = f.readline().strip()
                if first.startswith("gitdir:"):
                    p = first[7:].strip()
                    return p if os.path.isabs(p) else os.path.normpath(os.path.join(d, p))
            except OSError:
                return ""
        parent = os.path.dirname(d)
        if parent == d:
            return ""
        d = parent


def git_branch(cwd):
    """Branch name (or short SHA when detached) by reading .git/HEAD."""
    gitdir = _find_gitdir(cwd)
    if not gitdir:
        return ""
    try:
        with open(os.path.join(gitdir, "HEAD")) as f:
            head = f.read().strip()
    except OSError:
        return ""
    if head.startswith("ref: refs/heads/"):
        return head[16:]
    return head[:7]  # detached HEAD


def repo_url(data, cwd, branch):
    """Browse URL for the current branch: workspace.repo, else .git/config."""
    host = dig(data, "workspace", "repo", "host")
    owner = dig(data, "workspace", "repo", "owner")
    name = dig(data, "workspace", "repo", "name")
    if not (host and owner and name):
        remote = _origin_url(cwd)
        m = re.match(r"(?:git@|https?://)([^:/]+)[:/](.+?)/(.+?)(?:\.git)?/?$", remote)
        if not m:
            return ""
        host, owner, name = m.group(1), m.group(2), m.group(3)
    base = "https://{}/{}/{}".format(host, owner, name)
    if host == "github.com" and branch:
        return "{}/tree/{}".format(base, branch)
    return base


def _origin_url(cwd):
    gitdir = _find_gitdir(cwd)
    if not gitdir:
        return ""
    cfg = os.path.join(gitdir, "config")
    if not os.path.isfile(cfg):  # linked worktree: config lives in commondir
        try:
            with open(os.path.join(gitdir, "commondir")) as f:
                common = f.read().strip()
            common = common if os.path.isabs(common) else os.path.join(gitdir, common)
            cfg = os.path.join(os.path.normpath(common), "config")
        except OSError:
            return ""
    try:
        in_origin = False
        with open(cfg) as f:
            for line in f:
                line = line.strip()
                if line.startswith("["):
                    in_origin = line.replace("'", '"') == '[remote "origin"]'
                elif in_origin and line.startswith("url"):
                    _, _, val = line.partition("=")
                    return val.strip()
    except OSError:
        pass
    return ""


# ── gauge rendering ──
def zone_color(pos_pct):
    if pos_pct < WARN_PCT:
        return NEON_GREEN, ZONE_EC[0]
    if pos_pct < RED_PCT:
        return NEON_ORG, ZONE_EC[1]
    return NEON_RED, ZONE_EC[2]


def ctx_gauge(pct, bar_len):
    """Zoned gauge: cells tint green/amber/red by position (visible redline)."""
    pct_c = clamp(pct, 0, 100)
    units = pct_c * bar_len * 8 // 100
    out = ""
    for i in range(bar_len):
        fc, ec = zone_color((i + 0.5) * 100 / bar_len)
        bg = ec.replace("38;5;", "48;5;")
        u = clamp(units - i * 8, 0, 8)
        if u == 8:
            out += fc + _FULL + R
        elif u == 0:
            out += bg + " " + R
        else:
            out += bg + fc + _FRAC[u] + R
    return out


def value_color(pct):
    if pct < WARN_PCT:
        return NEON_GREEN
    if pct < RED_PCT:
        return NEON_ORG
    return NEON_RED


def rate_mirror(pct_5h, pct_7d, len_5h, len_7d, lbl_5h, lbl_7d):
    """5h gauge fills right-to-left, 7d left-to-right, meeting at center.

    Bar lengths are per-side: in cycle mode each gauge stretches to absorb
    its label's phase width difference, so the segment footprint and the
    center divider stay put with no padding blanks.
    """
    fc_5h = value_color(pct_5h) if pct_5h >= WARN_PCT else RL_5H_FC
    fc_7d = value_color(pct_7d) if pct_7d >= WARN_PCT else RL_7D_FC
    bg_5h = RL_5H_EC.replace("38;5;", "48;5;")
    bg_7d = RL_7D_EC.replace("38;5;", "48;5;")
    bg_fc_5h = fc_5h.replace("1;38;5;", "48;5;").replace("38;5;", "48;5;")
    p5, p7 = clamp(pct_5h, 0, 100), clamp(pct_7d, 0, 100)

    units = p5 * len_5h * 8 // 100
    full, frac = units // 8, units % 8
    empty = len_5h - full - (1 if frac else 0)
    left = "{}{}{} {}{}{}".format(fc_5h, lbl_5h, R, bg_5h, " " * empty, R)
    if frac:  # mirrored partial: bright bg, dark fg, inverted eighth-block
        left += "{}{}{}{}".format(bg_fc_5h, RL_5H_EC, _FRAC[8 - frac], R)
    left += "{}{}{}".format(fc_5h, _FULL * full, R)

    units = p7 * len_7d * 8 // 100
    full, frac = units // 8, units % 8
    empty = len_7d - full - (1 if frac else 0)
    right = "{}{}{}".format(fc_7d, _FULL * full, R)
    if frac:
        right += "{}{}{}{}".format(bg_7d, fc_7d, _FRAC[frac], R)
    right += "{}{}{} {}{}{}".format(bg_7d, " " * empty, R, fc_7d, lbl_7d, R)

    return "{}{}|{}{}".format(left, DIM, R, right)


# ── payload access ──
def dig(data, *keys):
    cur = data
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def num(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


# ── agent presence: what the session's agent is doing ──
# Only entry type, stop reason, error flag and timestamp are read — never
# message text, beyond a 40-char prefix test for harness markers.
TAIL_BYTES = 64 * 1024    # transcript tail read on every refresh
TAIL_MAX = 1024 * 1024    # widened read when one huge line hides every message
IDLE_S = 10 * 60          # "yours" this long → idle
SLEEP_S = 60 * 60         # "yours" this long → asleep
ERROR_WINDOW_S = 60       # ≥ 2 failed tool results within this window …
ERROR_HOLD_S = 30         # … hold the error state this long after the newest
_HARNESS_MARKERS = ("<command-name>", "<local-command-stdout>",
                    "<local-command-caveat>")
_TURN_ENDS = ("end_turn", "stop_sequence", "max_tokens", "refusal")


def parse_ts(s):
    """Transcript ISO-8601 UTC timestamp → epoch seconds, or None."""
    if not isinstance(s, str) or len(s) < 19:
        return None
    try:
        t = calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None
    m = re.match(r"\.(\d+)", s[19:])
    return t + float("0." + m.group(1)) if m else t


def tail_entries(path, limit=TAIL_BYTES):
    """Parse the JSONL entries in the last `limit` bytes of a transcript.

    Returns (entries oldest→newest, bytes read). The cut first line is
    dropped. If no message entry survives (one huge line can fill the
    window) the read widens once, up to TAIL_MAX.
    """
    try:
        with open(path, "rb") as f:
            size = f.seek(0, 2)
            while True:
                start = max(size - limit, 0)
                f.seek(start)
                buf = f.read(limit)
                lines = buf.split(b"\n")
                if start > 0:
                    lines = lines[1:]
                entries = []
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        e = json.loads(line.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    if isinstance(e, dict):
                        entries.append(e)
                if start == 0 or limit >= TAIL_MAX or any(
                        e.get("type") in ("user", "assistant") for e in entries):
                    return entries, len(buf)
                limit = TAIL_MAX
    except (OSError, TypeError, ValueError):
        return [], 0


def _classify(e):
    """(activity, ts, is_error) for a message entry, or None to skip it."""
    kind = e.get("type")
    if kind not in ("user", "assistant") or e.get("isMeta"):
        return None
    ts = parse_ts(e.get("timestamp"))
    msg = e.get("message")
    if ts is None or not isinstance(msg, dict):
        return None
    if kind == "assistant":
        return ("yours" if msg.get("stop_reason") in _TURN_ENDS else "working"), ts, False
    content = msg.get("content")
    if isinstance(content, str):
        first = content
    elif isinstance(content, list) and content and isinstance(content[0], dict):
        first = content[0].get("text") if content[0].get("type") == "text" else ""
    else:
        return None
    head = (first or "")[:40] if isinstance(first, str) else ""
    if head.startswith(_HARNESS_MARKERS):
        return None
    if head.startswith("[Request interrupted"):
        return "yours", ts, False
    err = isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error") is True
        for b in content)
    return "working", ts, err


def _decay(state, since, now, idle_s, sleep_s):
    if state == "yours" and now - since >= sleep_s:
        return "asleep"
    if state == "yours" and now - since >= idle_s:
        return "idle"
    return state


def agent_state(entries, now, idle_s=IDLE_S, sleep_s=SLEEP_S):
    """(state, since) from transcript entries (oldest→newest).

    state: error | working | yours | idle | asleep | unknown. `since` is
    the newest message entry's timestamp (the newest error's for `error`).
    """
    newest, errors = None, []
    for e in entries:
        c = _classify(e) if isinstance(e, dict) else None
        if c is None:
            continue
        newest = c
        if c[2]:
            errors.append(c[1])
    if newest is None:
        return "unknown", 0
    if errors:
        last = max(errors)
        burst = sum(1 for t in errors if t >= last - ERROR_WINDOW_S)
        if burst >= 2 and now - last < ERROR_HOLD_S:
            return "error", last
    state, since = newest[0], newest[1]
    return _decay(state, since, now, idle_s, sleep_s), since


# ── presence: hooks layer, state file, bubbles ──
HOOK_STATES = ("working", "yours", "needs")
STATE_BUBBLE_S = 30        # state-change bubbles show this long
EVENT_TTL_S = 30           # default lifetime of an events-channel bubble
QUIP_EVERY_S = 20 * 60     # at most one idle quip per this many seconds
PRUNE_AGE_S = 7 * 86400    # cache files untouched this long are removed
PRUNE_EVERY_S = 3600
_CACHE_SUFFIXES = (".state.json", ".events.jsonl", ".hooks.jsonl", ".sid")
WAVE_EVENT = "wave"        # events-channel text that makes the sprite wave
_SID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
QUIPS = ("all quiet.", "systems nominal", "standing by", "scanning sector 7",
         "orbit stable", "insert coin", "beep boop", "0 bogeys on scope",
         "buffer empty", "ping?", "hello, operator", "stars look nice",
         "*hums quietly*", "charging lasers", "awaiting orders")


def _tail_lines(path, limit):
    """Parsed JSON objects from the last `limit` bytes of a JSONL file."""
    try:
        with open(path, "rb") as f:
            size = f.seek(0, 2)
            start = max(size - limit, 0)
            f.seek(start)
            lines = f.read(limit).split(b"\n")
    except (OSError, TypeError, ValueError):
        return []
    out = []
    for line in lines[1:] if start else lines:
        try:
            e = json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def _num_or_none(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def read_hooks(path):
    """[(ts, state, src)] from the hook log, oldest→newest."""
    out = []
    for e in _tail_lines(path, 4096):
        ts = _num_or_none(e.get("ts"))
        if ts is not None and e.get("state") in HOOK_STATES:
            src = e.get("src")
            out.append((ts, e["state"], src if isinstance(src, str) else ""))
    return out


def merge_hooks(state, since, hooks, now, idle_s=IDLE_S, sleep_s=SLEEP_S):
    """Let hook-reported state that is newer than the transcript win.

    Hooks see what the transcript cannot (a pending permission prompt).
    An idle_prompt notification never papers over a pending `needs`; a
    run of the same state keeps its first timestamp so idle/asleep decay
    counts from when the turn really ended. An error burst always stands.
    """
    if state == "error" or not hooks:
        return state, since
    i = len(hooks) - 1
    if hooks[i][2] == "idle_prompt":
        j = i - 1
        while j >= 0 and hooks[j][2] == "idle_prompt":
            j -= 1
        if j >= 0 and hooks[j][1] == "needs" and hooks[j][0] >= since - 1:
            i = j
    ts, hstate, _ = hooks[i]
    if state != "unknown" and ts < since - 1:  # 1 s slack for whole-second hook clocks
        return state, since
    while i > 0 and hooks[i - 1][1] == hstate:
        i -= 1
    hsince = hooks[i][0]
    return _decay(hstate, hsince, now, idle_s, sleep_s), hsince


def cache_dir(create=True):
    """Per-user presence cache dir, or "" if unusable.

    RETRO_HUD_CACHE_DIR, else ~/.cache/retro-hud, else (no HOME, or it
    can't be created) /tmp/retro-hud-<uid>. With create=False nothing is
    made: an existing directory is returned or "".
    """
    d = os.environ.get("RETRO_HUD_CACHE_DIR", "")
    home = os.environ.get("HOME", "")
    cands = [d] if d else ([os.path.join(home, ".cache", "retro-hud")] if home else [])
    if not d and hasattr(os, "getuid"):
        cands.append("/tmp/retro-hud-{}".format(os.getuid()))
    for c in cands:
        try:
            if create:
                os.makedirs(c, 0o700, exist_ok=True)
            elif not os.path.isdir(c):
                continue
            if c.startswith("/tmp/") and os.stat(c).st_uid != os.getuid():
                continue  # someone else's directory: never use it
            return c
        except OSError:
            continue
    return ""


def _read_json(path):
    try:
        with open(path) as f:
            obj = json.loads(f.read(65536))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


def _clean(text):
    return "".join(ch for ch in str(text) if ch.isprintable()).strip()


def newest_event(events, now):
    """(text, ts) of the newest unexpired events-channel entry, or ("", None)."""
    for e in reversed(events):
        ts = _num_or_none(e.get("ts"))
        ttl = _num_or_none(e.get("ttl"))
        text = e.get("text")
        if ts is None or not isinstance(text, str):
            continue
        ttl = EVENT_TTL_S if ttl is None else ttl
        if ts - 5 <= now < ts + ttl and _clean(text):
            return _clean(text), ts
    return "", None


def _icon_ok(icon):
    """One printable, visible code point (a letter, digit, punctuation
    or symbol), so it never takes zero cells or two glyphs."""
    return isinstance(icon, str) and len(icon) == 1 and \
        unicodedata.category(icon)[0] in "LNPS"


def newest_icon(events, now):
    """The `icon` of the newest unexpired events-channel entry that
    carries a valid one, or "". An icon may come with or without text."""
    for e in reversed(events):
        ts = _num_or_none(e.get("ts"))
        ttl = _num_or_none(e.get("ttl"))
        ttl = EVENT_TTL_S if ttl is None else ttl
        if ts is not None and ts - 5 <= now < ts + ttl and _icon_ok(e.get("icon")):
            return e["icon"]
    return ""


def next_bubble(prev, snap, now, event="", name="", quips=True, mode="alerts"):
    """(bubble text, state-file updates) for this refresh.

    Priority: the events channel → a state-change bubble (once per
    transition, STATE_BUBBLE_S) → a rare idle quip → an ambient z / zZ
    while dozing. Muted (mute_until in the future) → nothing at all.

    `mode` (RETRO_HUD_BUBBLES): "alerts" (default) keeps only what asks
    something of you — "need you", "compact?", "limit soon" — and events;
    "all" adds the narration ("ready", "hm.", z/zZ, quips); "off" says
    nothing at all. A bar that narrates was the first thing its owner
    turned off.
    """
    upd = {}
    state = snap["state"]
    pstate = prev.get("state")
    narrate = mode == "all"
    said = None
    if pstate is not None:  # the first sighting is not a transition
        if state != pstate and state == "error" and narrate:
            said = "hm."
        elif state != pstate and state == "needs":
            said = "need you"
        elif (_num_or_none(prev.get("ctx_pct")) or 0) < RED_PCT <= snap["ctx_pct"]:
            said = "compact?"
        elif (_num_or_none(prev.get("limit_pct")) or 0) < WARN_PCT <= snap["limit_pct"]:
            said = "limit soon"
        elif state != pstate and state == "yours" and narrate:
            said = "ready"
    bubble = prev.get("bubble") if isinstance(prev.get("bubble"), dict) else None
    if said:
        bubble = {"text": (name + ": " if name else "") + said,
                  "until": now + STATE_BUBBLE_S}
    if bubble and not (_num_or_none(bubble.get("until")) or 0) > now:
        bubble = None
    last_quip = _num_or_none(prev.get("last_quip")) or 0
    if bubble is None and not event and quips and narrate and state == "idle" \
            and now - last_quip >= QUIP_EVERY_S:
        bubble = {"text": QUIPS[int(now // QUIP_EVERY_S) % len(QUIPS)],
                  "until": now + STATE_BUBBLE_S}
        upd["last_quip"] = now
    upd["bubble"] = bubble
    if mode == "off" or (_num_or_none(prev.get("mute_until")) or 0) > now:
        return "", upd
    text = event or (bubble or {}).get("text") or \
        ({"idle": "z", "asleep": "zZ"}.get(state, "") if narrate else "")
    return trunc(_clean(text), BUBBLE_MAX), upd


def _prune(d, now, keep):
    try:
        for n in os.listdir(d):
            if n.endswith(_CACHE_SUFFIXES) and not n.startswith(keep):
                p = os.path.join(d, n)
                try:
                    if os.path.getmtime(p) < now - PRUNE_AGE_S:
                        os.remove(p)
                except OSError:
                    pass
    except OSError:
        pass


def _write_json(path, obj):
    tmp = "{}.{}.tmp".format(path, os.getpid())
    try:
        with open(tmp, "w") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
        return True
    except (OSError, TypeError, ValueError):
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


SESSIONS_FRESH_S = 15 * 60   # a state file older than this is a session that is gone


def other_sessions(sid, now):
    """(live, needing) counts of the OTHER Claude sessions this machine's
    presence cache knows (RETRO_HUD_SESSIONS=1): state files written in the
    last SESSIONS_FRESH_S seconds, this session's own left out. Cache reads
    only — the handler asks tmux which of them are on screen."""
    d = cache_dir(create=False)
    if not d:
        return 0, 0
    live = needing = 0
    try:
        names = os.listdir(d)
    except OSError:
        return 0, 0
    for name in names:
        if not name.endswith(".state.json") or name[:-11] == sid:
            continue
        path = os.path.join(d, name)
        try:
            if now - os.path.getmtime(path) > SESSIONS_FRESH_S:
                continue
            st = _read_json(path).get("state")
        except OSError:
            continue
        live += 1
        if st == "needs":
            needing += 1
    return live, needing


def card_facts(data):
    """What the status card (retro-hud://card) shows beyond the gauges, from
    this refresh's payload: model, effort, session duration (s), lines
    added / removed, working directory's basename. Only what is there."""
    out = {}
    model = dig(data, "model", "display_name") or dig(data, "model", "id")
    if isinstance(model, str) and model.strip():
        out["model"] = model.strip()[:40]
    effort = dig(data, "effort", "level")
    if isinstance(effort, str) and effort.strip():
        out["effort"] = effort.strip()[:12]
    dur = _num_or_none(dig(data, "cost", "total_duration_ms"))
    if dur is not None:
        out["dur_s"] = int(max(dur, 0) // 1000)
    for key, src in (("lines_add", "total_lines_added"), ("lines_del", "total_lines_removed")):
        v = _num_or_none(dig(data, "cost", src))
        if v is not None:
            out[key] = int(v)
    cwd = dig(data, "workspace", "current_dir") or data.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        out["dir"] = (os.path.basename(cwd.rstrip(os.sep)) or cwd)[:40]
    return out


def presence(data, now, gauge_pct, ctx_pct, limit_pct, cost, creature=False):
    """Agent presence for this refresh: {"mood", "bubble", "since",
    "sprite", "mood_since", "seed", "icon"}, or None for the plain gauge
    alien (presence off, or the agent's state is unknown). Never raises;
    any IO failure degrades to no bubble.

    `mood_since` is when the current mood began, kept in the state file
    (None when it can't be written); `seed` is the state file's raw
    `seed`. With `creature`, `sprite` may also name a creature family."""
    if os.environ.get("RETRO_HUD_PRESENCE", "1") == "0":
        return None
    idle_s = (num(os.environ.get("RETRO_HUD_IDLE_MIN")) or IDLE_S // 60) * 60
    sleep_s = (num(os.environ.get("RETRO_HUD_SLEEP_MIN")) or SLEEP_S // 60) * 60
    path = data.get("transcript_path")
    entries = tail_entries(path)[0] if isinstance(path, str) and path else []
    state, since = agent_state(entries, now, idle_s, sleep_s)
    sid = data.get("session_id")
    sid = sid if isinstance(sid, str) and _SID_RE.fullmatch(sid) else ""
    if sid:  # the hooks layer, if installed, knows what the transcript can't
        d = cache_dir(create=False)
        if d:
            state, since = merge_hooks(state, since,
                                       read_hooks(os.path.join(d, sid + ".hooks.jsonl")),
                                       now, idle_s, sleep_s)
    if state == "unknown":
        return None
    sprite = os.environ.get("RETRO_HUD_SPRITE", "alien")
    bubble = icon = ""
    wave_since = mood_since = seed = None
    mood = pick_mood(gauge_pct, state)
    d = cache_dir() if sid else ""
    if d:
        sp = os.path.join(d, sid + ".state.json")
        prev = _read_json(sp)
        if prev.get("sprite") in SPRITES or (creature and prev.get("sprite") in FAMILIES):
            sprite = prev["sprite"]
        seed = prev.get("seed")
        snap = {"state": state, "since": since, "ctx_pct": ctx_pct,
                "limit_pct": limit_pct, "cost": cost}
        snap.update(card_facts(data))
        events = _tail_lines(os.path.join(d, sid + ".events.jsonl"), 16384)
        event, ets = newest_event(events, now)
        icon = newest_icon(events, now) if creature else ""
        if event == WAVE_EVENT:  # a gesture, not words: wave instead
            event, wave_since = "", ets
        name = _clean(os.environ.get("RETRO_HUD_AGENT_NAME", ""))
        quips = os.environ.get("RETRO_HUD_QUIPS", "1") != "0"
        mode = os.environ.get("RETRO_HUD_BUBBLES", "alerts")
        if mode not in ("alerts", "all", "off"):
            mode = "alerts"
        text, upd = next_bubble(prev, snap, now, event, name, quips, mode)
        rec = dict(prev)
        rec.update(snap)
        rec.update(upd)
        rec["updated"] = now
        if prev.get("mood") == mood and _num_or_none(prev.get("mood_since")) is not None:
            rec["mood_since"] = prev["mood_since"]
        else:  # a new mood (or the first sighting): its entry tics start now
            rec["mood"], rec["mood_since"] = mood, now
        if creature:  # for the click menu, which can't see this environment
            rec["creature"] = creature_family(sprite)
        else:
            rec.pop("creature", None)
        if now - (_num_or_none(prev.get("last_prune")) or 0) >= PRUNE_EVERY_S:
            _prune(d, now, sid + ".")
            rec["last_prune"] = now
        if _write_json(sp, rec):
            bubble = text
            mood_since = rec["mood_since"]
            _map_pane(d, sid)
    if wave_since is not None and mood not in ("red", "error", "agitated"):
        # waves in place for the event's ttl; the gesture is not stored,
        # and it is not a mood change either: arms up at once, no scatter
        mood, since, mood_since = "yours", wave_since, wave_since - SCATTER_S
    return {"mood": mood, "bubble": bubble, "since": since, "sprite": sprite,
            "mood_since": mood_since, "seed": seed, "icon": icon}


def _map_pane(d, sid):
    """With click actions on inside tmux, record which session this pane
    shows (<cache>/pane-<N>.sid holds the session id) so the handler's
    agent menu can find the state and events files. Rewritten only when
    it changes; best effort."""
    pane = os.environ.get("TMUX_PANE", "")
    if not actions_on() or not _PANE_RE.match(pane):
        return
    path = os.path.join(d, "pane-{}.sid".format(pane[1:]))
    try:
        with open(path) as f:
            if f.read(256) == sid:
                return
    except OSError:
        pass
    tmp = "{}.{}.tmp".format(path, os.getpid())
    try:
        with open(tmp, "w") as f:
            f.write(sid)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ── pixel creature (RETRO_HUD_CREATURE, on by default) ──
# The agent's presence as a small mirrored pixel monster generated from a
# seed. tiny (the default): a 10×4-dot body in braille on the top rule.
# big and tall: a 9×4 body in half blocks (one text cell carries two pixel
# rows), straddling rows 1 and 2 (big) or with its upper half on a head
# line above row 1 (tall). It owns a fixed box and nothing else: the
# segments, corners and row 2's readings never move.
FAMILIES = ("blob", "beast", "alien", "bot", "robot")
_FAMILY_ALIAS = {"cat": "beast", "ghost": "blob"}  # robot is its own family since 3.1
CREATURE_COLORS = {"pink": 198, "green": 46, "purple": 135, "cyan": 45, "orange": 202}
CREATURE_PALETTE = (198, 46, 135, 45)  # seeded body colours; orange is for warnings
# RETRO_HUD_CREATURE_COLOR=mood: the seed's colour stays the body's (so
# sessions still tell apart) and only attention states recolour it
MOOD_256 = {"needs": 226, "error": 198, "idle": 65, "asleep": 240, "agitated": 214, "red": 196}
CREATURE_ATTEMPTS = 16
_M32 = 0xFFFFFFFF


def _mulberry32(seed):
    """Small seeded PRNG (floats in [0, 1)), identical on every Python."""
    s = seed & _M32

    def rand():
        nonlocal s
        s = (s + 0x6D2B79F5) & _M32
        t = ((s ^ (s >> 15)) * (1 | s)) & _M32
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & _M32)) & _M32) ^ t
        return ((t ^ (t >> 14)) & _M32) / 4294967296
    return rand


def _seed_of(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v & _M32
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
        if re.fullmatch(r"-?[0-9]{1,30}", v):
            return int(v) & _M32
        return zlib.crc32(v.encode("utf-8", "replace")) & _M32
    return None


def creature_seed(state=None, env="", sid=""):
    """The creature's seed: the state file's `seed`, else
    RETRO_HUD_CREATURE_SEED, else the session id, else 0. Integers (or
    integer strings) are taken as they are, other strings hashed with
    CRC-32, so a seed means the same creature on every Python."""
    for v in (state, env, sid):
        s = _seed_of(v)
        if s is not None:
            return s
    return 0


def pinned_color(pin):
    """A RETRO_HUD_CREATURE_COLOR value (a name or 0–255) as a 256-colour
    index, "mood" for the mood colours, or None when it names no colour."""
    pin = str(pin or "").strip().lower()
    if pin == "mood":
        return "mood"
    if pin in CREATURE_COLORS:
        return CREATURE_COLORS[pin]
    if pin.isdigit() and int(pin) <= 255:
        return int(pin)
    return None


def creature_color(seed, pin=""):
    """256-colour index of the body: RETRO_HUD_CREATURE_COLOR (a name or
    0–255) pins it, else one of CREATURE_PALETTE chosen by the seed."""
    pinned = pinned_color(pin)
    if pinned is not None and pinned != "mood":
        return pinned
    return CREATURE_PALETTE[int(_mulberry32(seed ^ 0x5EED)() * len(CREATURE_PALETTE))]


def creature_family(name):
    """A family name, or a 2.x sprite-set name mapped to its family."""
    if name in FAMILIES:
        return name
    return _FAMILY_ALIAS.get(name, "alien") if isinstance(name, str) else "alien"


def _grid_from(rows):
    k = {".": None, "X": "body", "E": "eye"}
    return tuple(tuple(k[ch] for ch in row) for row in rows)


FALLBACK_GRID = _grid_from(("..X...X..",
                            ".XEXXXEX.",
                            "XXXXXXXXX",
                            ".X..X..X."))
FALLBACK_TINY = _grid_from(("..X....X..",
                            ".XEXXXXEX.",
                            "XXXXXXXXXX",
                            ".X..XX..X."))

# Per-family fill probabilities for pixel rows 0–2, half-body columns
# 0–4 (column 4 is the centre); row 3 (legs) and the eyes are placed by
# rule in _grow.
_FAMILY_PROBS = {
    "alien": ((0, 0, .45, .35, .25), (0, .1, .6, .95, 1), (.35, .85, 1, 1, 1)),
    "beast": ((0, .4, .5, .3, .2), (.2, .7, 1, 1, 1), (.8, 1, 1, 1, 1)),
    "blob": ((0, .2, .8, 1, 1), (.4, 1, 1, 1, 1), (.6, 1, 1, 1, 1)),
}


def _grow(rand, family):
    """One candidate half body: 4 rows × 5 columns of None/body/eye."""
    h = [[None] * 5 for _ in range(4)]
    if family == "bot":  # square: a block with flat top, antenna or ears
        left = 0 if rand() < .5 else 1
        for r in (1, 2):
            for c in range(left, 5):
                h[r][c] = "body"
        top = int(rand() * 3)
        for c in range(left, 5):
            if top == 0 or (top == 1 and c == 4) or (top == 2 and c == left):
                h[0][c] = "body"
        eye = left + 1
        leg = 2 if rand() < .5 else 3
        h[3][max(leg, left)] = "body"
    else:
        for r, probs in enumerate(_FAMILY_PROBS[family]):
            for c, p in enumerate(probs):
                if rand() < p:
                    h[r][c] = "body"
        eye = 2 if rand() < .5 else 3
        if family == "blob":  # a wide base instead of legs
            for c in range(1 + int(rand() * 3), 5):
                h[3][c] = h[2][c] = "body"
        else:
            leg = 1 + int(rand() * (2 if family == "alien" else 3))
            h[3][leg] = h[2][leg] = "body"
            if family == "alien":
                h[3][4] = "body"  # the third, middle leg
            elif leg > 1 and rand() < .4:
                h[3][leg - 1] = h[2][leg - 1] = "body"  # a thick leg
            for c in range(leg, 5):
                h[2][c] = "body"
    h[1][4] = h[2][4] = "body"  # spine
    for c in range(eye + 1, 5):
        h[1][c] = "body"        # body between the eyes
    h[1][eye] = "eye"
    return h


def creature_grid(seed, family="alien", attempts=CREATURE_ATTEMPTS, width=9):
    """The creature's body: 4 pixel rows × `width` columns of None, "body"
    or "eye" (a tuple of tuples): 9 for the half-block creature, 10 for
    the braille one (the centre column doubled). Mirrored left/right,
    4-connected, two eyes on row 1 with body between them, at least two
    cells of legs on row 3. Deterministic per (seed, family, width); after `attempts` candidates
    that break a rule it returns FALLBACK_GRID (or FALLBACK_TINY at width
    10). The robot is built from robot_parts, never grown."""
    family = creature_family(family)
    rand = _mulberry32(seed ^ zlib.crc32(family.encode()))
    last = width - 1
    for _ in range(attempts + (family == "robot")):  # the robot is built, never grown
        h = _robot_half(robot_parts(seed)) if family == "robot" else _grow(rand, family)
        g = [[h[r][min(c, last - c)] for c in range(width)] for r in range(4)]
        seen, todo = {(1, 4)}, [(1, 4)]  # keep what touches the spine
        while todo:
            r, c = todo.pop()
            for n in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if 0 <= n[0] < 4 and 0 <= n[1] < width and g[n[0]][n[1]] and n not in seen:
                    seen.add(n)
                    todo.append(n)
        for r in range(4):
            for c in range(width):
                if (r, c) not in seen:
                    g[r][c] = None
        if sum(1 for v in g[1] if v == "eye") == 2 and sum(1 for v in g[3] if v) >= 2:
            return tuple(tuple(row) for row in g)
    return FALLBACK_GRID if width == 9 else FALLBACK_TINY


# ── the robot family: 12×8 dots, parts picked by the seed ──
# Eight dot rows (two braille text rows): antenna | head top | eyes | chin
# or neck | shoulders | torso (chest) | legs | feet. Built from parts
# rather than grown, so every seed is unmistakably a robot: flat head,
# square eyes or a visor, boxy torso, arms, legs or treads. Mirrored.
# "hole" cells (the chest panel or lights) are unlit dots that never
# blink. At 4 rows (tiny, the half-block pose) the same parts make a
# 10×4 (9×4) robot: antenna, head with eye holes, body, legs.
ROBOT_COLS, ROBOT_ROWS = 12, 8
ROBOT_W = 9               # its box in cells: 12 body dots + 3 each side
_ROBOT_OPTS = {"antenna": ("one", "two", "dish", "ears", "flat"),
               "eyes": ("squares", "squares", "visor", "dots"),
               "neck": (True, False),
               "arms": ("down", "down", "out", "up", "none"),
               "chest": ("panel", "panel", "lights", "plain"),
               "legs": ("legs", "legs", "treads", "pole"),
               "torso": (8, 10, 10, 12)}


def robot_parts(seed):
    """The robot's parts for `seed`: {"antenna", "eyes", "neck", "arms",
    "chest", "legs", "head" (6, 8 or 10 dots), "torso" (8, 10 or 12)}."""
    rand = _mulberry32(seed ^ zlib.crc32(b"robot"))
    parts = {}
    for k in ("antenna", "eyes", "neck", "arms", "chest", "legs", "torso"):
        opts = _ROBOT_OPTS[k]
        parts[k] = opts[int(rand() * len(opts))]
    heads = (8, 8, 10) if parts["eyes"] == "squares" else (6, 8, 10)  # squares need room
    parts["head"] = heads[int(rand() * len(heads))]
    return parts


def _robot_half(p):
    """The same robot at 4 rows: one candidate half body (4 rows × 5
    columns, column 4 the centre) for creature_grid, from robot_parts(p).
    Antenna or head top | head with one eye hole (two, mirrored) | body,
    arms out or not | legs, treads or a base (the pole)."""
    wide = p["head"] > 6
    head = (1, 2, 3, 4) if wide else (2, 3, 4)
    top = {"one": (4,), "two": (2,) if wide else (3,), "dish": head[1:],
           "ears": (0, 1, 2, 3, 4) if wide else (1, 2, 3, 4), "flat": head}[p["antenna"]]
    eye = (3 if p["eyes"] == "visor" else 2) if wide else 3
    body = (0, 1, 2, 3, 4) if p["arms"] != "none" else (1, 2, 3, 4)
    legs = {"treads": (0, 1, 2, 3, 4), "pole": (3, 4)}.get(  # a pole is a short base here
        p["legs"], (1, 2) if p["torso"] >= 10 else (2,))
    h = [[None] * 5 for _ in range(4)]
    for r, cols in enumerate((top, head, body, legs)):
        for c in cols:
            h[r][c] = "body"
    h[1][eye] = "eye"
    return h


def _centred(pattern, width=ROBOT_COLS):
    left = (width - len(pattern)) // 2
    return "." * left + pattern + "." * (width - len(pattern) - left)


def robot_grid(seed):
    """The robot's body: ROBOT_ROWS × ROBOT_COLS of None, "body", "eye" or
    "hole" (a tuple of tuples), from robot_parts(seed)."""
    p = robot_parts(seed)
    W, hw, tw = ROBOT_COLS, p["head"], p["torso"]
    hl, tl = (W - hw) // 2, (W - tw) // 2
    arm = max(tl - 2, 0)                      # the arms' column (and its mirror)
    rows = [{"one": _centred("XX"), "two": _centred("X" + "." * (hw - 4) + "X"),
             "dish": _centred("X" * (hw - 2)), "ears": _centred("X" * (hw + 2)),
             "flat": _centred("X" * hw)}[p["antenna"]],
            _centred("X" * hw)]
    inner = hw - 2
    rows.append(_centred({"squares": "X" + "EE" + "X" * (inner - 4) + "EE" + "X",
                          "visor": "X" + "E" * inner + "X",
                          "dots": "XE" + "X" * (inner - 2) + "EX"}[p["eyes"]]))
    rows.append(_centred("XX") if p["neck"] else _centred("X" * hw))
    torso = _centred("X" * tw)
    shoulders = _centred("X" * min(tw + 4, W)) if p["arms"] in ("down", "up") else torso
    if p["arms"] == "out":
        shoulders = "X" * W
    chest = list(torso)
    if p["chest"] == "panel":
        chest[5] = chest[6] = "H"
    elif p["chest"] == "lights":
        for c in (4, 7) + ((2, 9) if tl <= 1 else ()):
            chest[c] = "H"
    chest = "".join(chest)

    def with_arms(row):
        r = list(row)
        r[arm] = r[W - 1 - arm] = "X"
        return "".join(r)
    if p["arms"] == "up":
        rows[3] = with_arms(rows[3])
    rows += [shoulders, with_arms(chest) if p["arms"] == "down" else chest]
    if p["legs"] == "legs":
        rows += ["...XX..XX...", "...XX..XX..." if tw == 8 else "..XXX..XXX.."]
    elif p["legs"] == "treads":
        rows += ["XX.X.XX.X.XX", "X" * W]
    else:
        rows += [_centred("XX"), _centred("X" * 8)]
    k = {".": None, "X": "body", "E": "eye", "H": "hole"}
    return tuple(tuple(k[ch] for ch in row) for row in rows)


BOX_W = 13                # the creature's footprint: 9 body cells + 2 each side
CREATURE_MIN_TRACK = BOX_W + 4
# rule cells (dots for the tiny creature) per tick; 0 parks: walk to the
# left end of the rule and stay
CREATURE_SPEEDS = {"calm": 1, "agitated": 2, "red": 4, "error": 0, "working": 3,
                   "yours": 1, "needs": 0, "idle": 0, "asleep": 0}
SCATTER_S = 10            # pixels scatter and reassemble this long after a mood starts
JUMP_S = 5                # "yours" jumps this long after it starts
SPIN_S = 20               # the red zone spins this long, then shakes
EYE_COLORS = {"needs": 226, "idle": 244}  # else white (255)
AMBER, RED_256, WHITE_256, ICON_256 = 214, 196, 255, 226
WANDER_REST = 64          # free-wandering ticks per stretch (plus the rule's length)
BLINK_P, HOP_P = 1 / 7, 1 / 12
_NO_BLINK = ("asleep", "error", "idle")  # closed, x-eyed, or blinking slowly


def _wander(seed, tick, span, speed):
    """(position, walking right) at `tick` on a track of `span` + 1
    positions: ease toward a seeded target, rest 2–6 ticks, pick another.

    A pure function of its inputs, so a refresh never re-rolls: time is
    cut into stretches of WANDER_REST + span ticks, each starting at a
    seeded anchor and ending on the next one (it heads there in time), so
    the walk is continuous across stretches and costs at most one
    stretch of steps to replay."""
    if span <= 0:
        return 0, True
    speed = max(int(speed), 1)
    length = WANDER_REST + span
    k, i = divmod(int(tick), length)

    def anchor(n):
        return int(_mulberry32((seed ^ (n * 0x9E3779B1)) & _M32)() * (span + 1))

    rand = _mulberry32((seed ^ 0x7A11C ^ (k * 0x85EBCA6B)) & _M32)
    x, goal = anchor(k), anchor(k + 1)
    target, rest, right = x, int(rand() * 4), True
    for j in range(i):
        left = length - j  # steps left in this stretch, this one included
        if abs(goal - x) > (left - 2) * speed:  # head for the next anchor
            d = goal - x
            step = min(abs(d), speed)
        else:
            if rest > 0:
                rest -= 1
                continue
            if x == target:
                target = int(rand() * (span + 1))
            d = target - x
            step = max(1, min(speed, (abs(d) + 1) // 2))  # eases in near the target
        if d:
            x += step if d > 0 else -step
            right = d > 0
            if x == target:
                rest = 2 + int(rand() * 5)
    return x, right


def _roll(seed, tick, salt):
    return _mulberry32((seed ^ (int(tick) * 2654435761) ^ salt) & _M32)()


def alive_flags(seed, tick):
    """What the creature's body does on its own this tick: {"blink"
    (~1 in 7), "hop" (~1 in 12; only calm and working act on it),
    "breathe" (every 4th tick)}, from (seed, tick) alone."""
    return {"blink": _roll(seed, tick, 0xB11C) < BLINK_P,
            "hop": _roll(seed, tick, 0x4097) < HOP_P,
            "breathe": int(tick) % 4 == 0}


def _motion(seed, mood, el, mood_since, tick, tick_len, span, spin):
    """(pos, right) for a mood: parked moods walk left from where a calm
    wander stood when the mood began and stay at 0; the red zone holds
    still while it spins (`spin`); the rest wander at their speed."""
    speed = CREATURE_SPEEDS[mood]
    if mood == "yours" and el is not None and el < WAVE_S:
        speed = 0
    if speed == 0:
        if mood_since is None:
            return 0, False
        start = int(mood_since) // tick_len
        return max(_wander(seed, start, span, 1)[0] - max(tick - start, 0), 0), False
    if spin and mood == "red" and el is not None and el < SPIN_S:
        return _wander(seed, int(mood_since) // tick_len, span, speed)
    return _wander(seed, tick, span, speed)


def _rise(cv):
    return cv[1:] + [[None] * len(cv[0])]


def _shift(cv, dx):
    if dx > 0:
        return [[None] * dx + row[:-dx] for row in cv]
    if dx < 0:
        return [row[-dx:] + [None] * -dx for row in cv]
    return [row[:] for row in cv]


def _span(row):
    cs = [c for c, v in enumerate(row) if v]
    return (cs[0], cs[-1]) if cs else None


def _merge(a, b):
    """Row b over row a: b's pixels win, a fills b's holes."""
    return [y or x for x, y in zip(a, b)]


def _widen(row):
    s = _span(row)
    if not s:
        return row
    lo, hi = max(s[0] - 1, 0), min(s[1] + 1, len(row) - 1)
    return ["b" if lo <= c <= hi else None for c in range(len(row))]


def _breathe(cv, centre):
    """One column wider: the centre column doubles, the right half moves
    one column right (into the empty margin)."""
    return [row[:centre + 1] + [row[centre]] + row[centre + 1:-1] for row in cv]


def _scatter(cv, seed, tick, k):
    """Move k pixels to empty cells of the box, within the rows the pose
    occupies (so a melted creature keeps its head line empty). Seeded by
    (seed, tick, k): a refresh never re-rolls."""
    w, n = len(cv[0]), len(cv)
    rows = [r for r in range(n) if any(cv[r])]
    if not rows:
        return cv
    rand = _mulberry32(seed ^ (tick * 2654435761) ^ (k * 40503))
    full = [(r, c) for r in range(n) for c in range(w) if cv[r][c]]
    empty = [(r, c) for r in range(rows[0], rows[-1] + 1) for c in range(w)
             if not cv[r][c]]
    out = [row[:] for row in cv]
    for _ in range(min(k, len(full), len(empty))):
        r, c = full.pop(int(rand() * len(full)))
        nr, nc = empty.pop(int(rand() * len(empty)))
        out[nr][nc], out[r][c] = out[r][c], None
    return out


def _colour(seed, mood, color):
    """The body's 256-colour index: amber and red for the gauge zones,
    else `color` (a pinned index; "mood" takes MOOD_256 for the attention
    states, the seed's colour otherwise), else the seed's."""
    if mood == "agitated":
        return AMBER
    if mood == "red":
        return RED_256
    if color == "mood":
        color = MOOD_256.get(mood)
    return creature_color(seed) if color is None else color


def pose(seed, mood, mood_since, now, cols, family="alien", color=None, icon="",
         tick_len=1):
    """The half-block creature (big and tall) for this refresh, a pure
    function of its inputs.

    `cols` is the length of the rule it walks; `mood_since` is when the
    current mood began (None when unknown: steady poses only, no entry
    tics, no scatter); the frame index is now // tick_len. Returns {"pos":
    box offset on the rule, "right": walking right, "canvas": 4 pixel rows
    × 13 cells of None / "b" body / "e" eye / "x" x-eye, "body", "eye", "x":
    256-colour indices, "icon", "icon_row": 0 upper half / 1 lower half,
    "ask": column of a yellow "?" or None}.
    """
    mood = mood if mood in CREATURE_SPEEDS else "calm"
    tick_len = max(int(tick_len), 1)
    tick = int(now) // tick_len
    el = None if mood_since is None else max(now - mood_since, 0)
    grid = creature_grid(seed, family)
    cv = [[None, None] + [{"body": "b", "eye": "e"}.get(v) for v in row] + [None, None]
          for row in grid]
    pos, right = _motion(seed, mood, el, mood_since, tick, tick_len,
                         max(cols - BOX_W, 0), True)
    fl = alive_flags(seed, tick)

    body = _colour(seed, mood, color)
    eye = EYE_COLORS.get(mood, WHITE_256)
    ask = None
    if fl["breathe"] and mood != "needs":
        cv = _breathe(cv, 6)
    if fl["blink"] and mood not in _NO_BLINK:
        cv = [["b" if v == "e" else v for v in row] for row in cv]
    if mood == "working" and tick % 2:  # walk cycle: legs step out
        cv[3] = _shift([cv[3]], 1 if right else -1)[0]
    if mood in ("calm", "working") and fl["hop"]:
        cv = _rise(cv)
    elif mood == "yours":
        s = _span(cv[2])
        if s:
            cv[1][s[0] - 1] = cv[1][s[1] + 1] = "b"  # arms up
        if el is not None and el < JUMP_S:
            cv = _rise(cv)
    elif mood == "needs":
        if tick % 2:
            cv = _rise(cv)
    elif mood == "idle":
        cv = [[None] * BOX_W, _merge(cv[0], cv[1]), cv[2], cv[3]]
        if tick % 6 >= 4:  # slow blinks: shut for two ticks in six
            cv = [["b" if v == "e" else v for v in row] for row in cv]
    elif mood == "asleep":
        top = ["b" if v else None for v in _merge(cv[0], cv[1])]
        cv = [[None] * BOX_W, [None] * BOX_W, _widen(top), _widen(_merge(cv[2], cv[3]))]
    elif mood == "error":
        cv = [["x" if v == "e" else v for v in row] for row in cv]
        cv = _shift(cv, 1 if tick % 2 else -1)
    elif mood == "red":
        if el is not None and el < SPIN_S:
            phase = el * 4 // SPIN_S  # 0 face, 1 edge-on, 2 upside down, 3 edge-on
            if phase == 2:
                cv = cv[::-1]
            elif phase in (1, 3):  # edge-on: squeeze toward the middle column
                thin = [[None] * BOX_W for _ in range(4)]
                for r in range(4):
                    for c in range(BOX_W):
                        if cv[r][c]:
                            thin[r][6 + int((c - 6) / 2)] = cv[r][c]
                cv = thin
        else:
            cv = _shift(cv, 1 if tick % 2 else -1)
    elif mood == "agitated":
        for r in range(1, 4):
            for c in range(BOX_W):
                if cv[r][c] == "e":
                    cv[r - 1][c] = "e"  # wide eyes
    if el is not None and el < SCATTER_S:
        cv = _scatter(cv, seed, tick, 6 if el < SCATTER_S / 2 else 3)
    if mood == "needs":
        s = _span(_merge(cv[0], cv[1]))
        ask = min((s[1] if s else 10) + 1, BOX_W - 1)
    return {"kind": "half", "w": BOX_W, "pos": pos, "right": right, "canvas": cv,
            "body": body, "eye": eye, "x": 231 if body == 198 else 198, "icon": icon or "",
            "icon_row": 1 if mood == "asleep" else 0, "ask": ask}


# ── the tiny creature (RETRO_HUD_CREATURE=tiny, the default) ──
# The same body at 10×4 dots, drawn in braille (2×4 dots per text cell) on
# the top rule only: the HUD keeps two lines. It owns a fixed 7-cell box
# and moves in half cells (a one-dot shift re-rasterises the cells).
TINY_W = 7                # box cells: 14 dot columns
TINY_MIN_TRACK = TINY_W + 4
# The alien family keeps the 2.x text-art guy at dot scale: two round eyes
# (2×2-dot holes, one dot apart, the "o.o"), arms splayed up and out from
# the top corners (the "/" and "\"), a compact body under them. Its arms
# carry the old mood vocabulary: pulled in and down when agitated (">o.o<"),
# straight up in the red zone ("\o.o/").
TINY_ALIEN = ("X.XXXXX.X",
              ".XEEXEEX.",
              ".XEEXEEX.",
              "..XXXXX..")
_ARMS = {"out": ((0, 0), (0, 8)), "up": ((0, 0), (1, 0), (0, 8), (1, 8)),
         "down": ((2, 0), (3, 0), (2, 8), (3, 8))}
TINY_ALIEN_COLOR = 46     # green, as the old guy: amber and red escalate it


def _tiny_body(seed, family):
    """4 rows × 14 dot columns, the body from dot column 1."""
    if creature_family(family) == "alien":
        rows = _grid_from(TINY_ALIEN)
    else:
        rows = creature_grid(seed, family, width=10)
    return [[None] + [{"body": "b", "eye": "e"}.get(v) for v in row] +
            [None] * (2 * TINY_W - 1 - len(row)) for row in rows]


def _arms(cv, which):
    for r, c in _ARMS["out"]:
        cv[r][c + 1] = None
    for r, c in _ARMS[which]:
        cv[r][c + 1] = "b"
    return cv


def _shut(cv, alien):
    """Eyes closed: the alien's round eyes narrow to a one-dot slit (its
    "-.-"), a generated body's eye holes fill."""
    out = [row[:] for row in cv]
    for r in range(4):
        if alien and r != 1:
            continue
        out[r] = ["b" if v == "e" else v for v in out[r]]
    return out


def tiny_pose(seed, mood, mood_since, now, cols, family="alien", color=None, icon="",
              tick_len=1):
    """The braille creature for this refresh, a pure function of its
    inputs (as pose()). `cols` is the rule's length in cells; motion is
    in dots, two per cell. Returns {"pos": box offset in cells, "sub":
    0/1 dot offset inside it, "right", "dots": 4 rows × 14 dot columns of
    None / "b" / "e" (an eye: a hole), "body": 256-colour index, "icon",
    "ask": cell of a yellow "?" or None}."""
    mood = mood if mood in CREATURE_SPEEDS else "calm"
    tick_len = max(int(tick_len), 1)
    tick = int(now) // tick_len
    el = None if mood_since is None else max(now - mood_since, 0)
    alien = creature_family(family) == "alien"
    cv = _tiny_body(seed, family)
    dw = 2 * TINY_W
    dot, right = _motion(seed, mood, el, mood_since, tick, tick_len,
                         2 * max(cols - TINY_W, 0), False)
    pos, sub = divmod(dot, 2)
    fl = alive_flags(seed, tick)

    if alien:
        if mood == "agitated":
            cv = _arms(cv, "down")
        elif mood == "red" or (mood == "yours" and tick % 2 == 0):
            cv = _arms(cv, "up")  # the red zone throws them up; "yours" waves
    if fl["breathe"] and mood not in ("needs", "asleep"):
        cv = _breathe(cv, 5)
    if fl["blink"] and mood not in _NO_BLINK:
        cv = _shut(cv, alien)
    if mood == "working" and tick % 2 and not alien:  # walk cycle: legs step out
        cv[3] = _shift([cv[3]], 1 if right else -1)[0]
    if mood in ("calm", "working") and fl["hop"]:
        cv = _rise(cv)
    elif mood == "yours":  # stops and waves
        if not alien:  # arm dots up beside the head, up and down
            s = _span(cv[2])
            if s:
                r = 0 if tick % 2 == 0 else 1
                cv[r][s[0] - 1] = cv[r][s[1] + 1] = "b"
        if el is not None and el < JUMP_S:
            cv = _rise(cv)
    elif mood == "needs":
        if tick % 2:
            cv = _rise(cv)
    elif mood == "idle":
        if tick % 6 >= 4:  # slow blinks: shut for two ticks in six
            cv = _shut(cv, alien)
    elif mood == "asleep":  # flat on the rule: the bottom two dot rows
        top = ["b" if v else None for v in _merge(_merge(cv[0], cv[1]), cv[2])]
        cv = [[None] * dw, [None] * dw, top, _widen(_merge(cv[2], cv[3]))]
    elif mood == "error":
        cv = _shift(cv, 1 if tick % 2 else -1)
    elif mood == "red":  # jitters
        cv = _shift(cv, int(_roll(seed, tick, 0x7E7) * 3) - 1)
    elif mood == "agitated" and not alien:
        for c in range(dw):
            if cv[1][c] == "e":
                cv[0][c] = "e"  # wide eyes
    if el is not None and el < SCATTER_S:
        cv = _scatter(cv, seed, tick, 6 if el < SCATTER_S / 2 else 3)
    cv = _shift(cv, sub)
    ask = None
    if mood == "needs":
        s = _span(_merge(_merge(cv[0], cv[1]), _merge(cv[2], cv[3])))
        ask = min((s[1] if s else 11) // 2 + 1, TINY_W - 1)
    if color is None:
        color = TINY_ALIEN_COLOR if alien else None
    return {"pos": pos, "sub": sub, "right": right, "dots": cv,
            "body": _colour(seed, mood, color), "icon": icon or "", "ask": ask}


def render_tiny(p):
    """The tiny creature's 7 rule cells: braille in the body colour,
    empty cells rule ─, every cell ending with an SGR reset; the "?" and
    an event icon in yellow."""
    cells = [(_sgr(p["body"]) + ch + R) if ch else (RULE + "─" + R)
             for ch in braille(p["dots"])]
    mark = lambda ch: "\033[1m" + _sgr(ICON_256) + ch + R
    if p.get("ask") is not None:
        cells[p["ask"]] = mark("?")
    icon = p.get("icon") or ""
    if icon:
        cells[TINY_W - vwidth(icon):] = [mark(icon)]
    return "".join(cells)


_BRAILLE_BITS = ((1, 8), (2, 16), (4, 32), (64, 128))


def braille(dots):
    """4 dot rows (even width) → one braille character per 2×4 dots, or
    None for a cell with no dot set. "e" (an eye) and "h" (a hole in the
    robot's chest) are unset: braille has one colour per cell, so eyes
    are dots left unset."""
    cells = []
    for ci in range(len(dots[0]) // 2):
        v = 0
        for r in range(4):
            for dc in range(2):
                tok = dots[r][2 * ci + dc]
                if tok and tok not in ("e", "h"):
                    v |= _BRAILLE_BITS[r][dc]
        cells.append(chr(0x2800 + v) if v else None)
    return cells


def _sgr(fg=None, bg=None):
    return "\033[{}m".format(";".join(
        ([] if fg is None else ["38;5;{}".format(fg)]) +
        ([] if bg is None else ["48;5;{}".format(bg)])))


def _half_cell(t, b, p):
    """One half-block cell for top pixel `t` over bottom pixel `b` (None,
    "b", "e" or "x") in pose `p`'s colours, ending with a reset; None
    when both are empty."""
    def colour(tok):
        return p["eye"] if tok == "e" else p["body"]

    if "x" in (t, b):
        return "\033[1m" + _sgr(p["x"], p["body"]) + "x" + R
    if t and b:
        return _sgr(colour(t), colour(b)) + "▀" + R
    if t:
        return _sgr(colour(t)) + "▀" + R
    if b:
        return _sgr(colour(b)) + "▄" + R
    return None


def render_box(p, rule_top=False):
    """(upper cells, lower cells) for a pose: two strings of visible
    width 13. One text cell holds two pixel rows (▀ top / ▄ bottom, fg
    and bg as their colours); every cell ends with an SGR reset. Empty
    cells are rule ─, except on the tall layout's head line (spaces)
    unless `rule_top`."""
    cv = p["canvas"]
    lines = []
    for row in (0, 1):
        cells = []
        for c in range(BOX_W):
            cell = _half_cell(cv[2 * row][c], cv[2 * row + 1][c], p)
            if cell is None:
                cell = " " + R if row == 0 and not rule_top else RULE + "─" + R
            cells.append(cell)
        lines.append(cells)
    mark = lambda ch: "\033[1m" + _sgr(ICON_256) + ch + R
    if p.get("ask") is not None:
        lines[0][p["ask"]] = mark("?")
    icon = p.get("icon") or ""
    if icon:
        w = vwidth(icon)
        row = lines[p.get("icon_row", 0)]
        row[BOX_W - w:] = [mark(icon)]
    return "".join(lines[0]), "".join(lines[1])


# ── the robot at big and tall: two braille rows ──
# robot_grid's 12×8 body in braille (2×4 dots per cell), the upper four
# dot rows on the upper text row (row 1 for big, the head line for tall),
# the lower four on the one below. It owns a ROBOT_W-cell box and moves
# in half cells like the tiny creature; the frames read the box width
# from the pose ("w"), so nothing else changes.
def _robot_body(seed):
    """8 rows × 2 * ROBOT_W dot columns, the body from dot column 3."""
    k = {"body": "b", "eye": "e", "hole": "h"}
    return [[None] * 3 + [k.get(v) for v in row] + [None] * 3 for row in robot_grid(seed)]


def _shut_eyes(cv):
    return [["b" if v == "e" else v for v in row] for row in cv]


def robot_pose(seed, mood, mood_since, now, cols, color=None, icon="", tick_len=1):
    """The robot for this refresh, a pure function of its inputs (as
    tiny_pose: `cols` is the rule's length in cells, motion in dots).
    Returns {"kind": "robot", "w": ROBOT_W, "pos": box offset in cells,
    "sub": 0/1 dot offset inside it, "right", "dots": 8 rows × 2 * ROBOT_W
    dot columns of None / "b" / "e" (an eye) / "h" (a chest hole), "body":
    256-colour index, "icon", "icon_row": 0 upper / 1 lower, "ask": cell of
    a yellow "?" or None}. Moods: it walks (legs step), hops, blinks and
    breathes; waves its arm tips beside the head when the turn is yours;
    bounces with a "?" when it needs you; blinks slowly when idle and
    powers down flat on the lower row when asleep; shakes on error,
    jitters in the red zone and widens its eyes when agitated."""
    mood = mood if mood in CREATURE_SPEEDS else "calm"
    tick_len = max(int(tick_len), 1)
    tick = int(now) // tick_len
    el = None if mood_since is None else max(now - mood_since, 0)
    cv = _robot_body(seed)
    dw = 2 * ROBOT_W
    dot, right = _motion(seed, mood, el, mood_since, tick, tick_len,
                         2 * max(cols - ROBOT_W, 0), False)
    pos, sub = divmod(dot, 2)
    fl = alive_flags(seed, tick)

    if fl["breathe"] and mood not in ("needs", "asleep"):
        cv = _breathe(cv, 8)
    if fl["blink"] and mood not in _NO_BLINK:
        cv = _shut_eyes(cv)
    if mood == "working" and tick % 2:  # walk cycle: the legs step out
        cv[6:] = _shift(cv[6:], 1 if right else -1)
    if mood in ("calm", "working") and fl["hop"]:
        cv = _rise(cv)
    elif mood == "yours":  # stops and waves: arm tips beside the head, up and down
        s = _span(cv[1])
        if s:
            r = 1 if tick % 2 == 0 else 2
            cv[r][s[0] - 1] = cv[r][s[1] + 1] = "b"
        if el is not None and el < JUMP_S:
            cv = _rise(cv)
    elif mood == "needs":
        if tick % 2:
            cv = _rise(cv)
    elif mood == "idle":
        if tick % 6 >= 4:  # slow blinks: shut for two ticks in six
            cv = _shut_eyes(cv)
    elif mood == "asleep":  # powered down: folded flat on the lower row
        cv = ([[None] * dw for _ in range(4)] +
              [_widen(_merge(cv[r], cv[r + 1])) for r in (0, 2, 4, 6)])
    elif mood == "error":
        cv = _shift(cv, 1 if tick % 2 else -1)
    elif mood == "red":  # jitters
        cv = _shift(cv, int(_roll(seed, tick, 0x7E7) * 3) - 1)
    elif mood == "agitated":
        for r in range(1, ROBOT_ROWS):
            for c in range(dw):
                if cv[r][c] == "e" and cv[r - 1][c] == "b":
                    cv[r - 1][c] = "e"  # wide eyes
    if el is not None and el < SCATTER_S:
        cv = _scatter(cv, seed, tick, 6 if el < SCATTER_S / 2 else 3)
    cv = _shift(cv, sub)
    ask = None
    if mood == "needs":
        top = cv[0]
        for r in range(1, 4):
            top = _merge(top, cv[r])
        s = _span(top)
        ask = min((s[1] if s else dw - 3) // 2 + 1, ROBOT_W - 1)
    return {"kind": "robot", "w": ROBOT_W, "pos": pos, "sub": sub, "right": right, "dots": cv,
            "body": _colour(seed, mood, color), "icon": icon or "",
            "icon_row": 1 if mood == "asleep" else 0, "ask": ask}


def render_robot(p, rule_top=False):
    """(upper cells, lower cells) for a robot pose: two strings of visible
    width ROBOT_W, braille in the body colour, every cell ending with an
    SGR reset. Empty cells are rule ─, except on the tall layout's head
    line (spaces) unless `rule_top`; the "?" and an event icon in yellow."""
    cv = p["dots"]
    lines = []
    for half in (0, 1):
        cells = []
        for ch in braille(cv[4 * half:4 * half + 4]):
            if ch:
                cells.append(_sgr(p["body"]) + ch + R)
            else:
                cells.append(" " + R if half == 0 and not rule_top else RULE + "─" + R)
        lines.append(cells)
    mark = lambda ch: "\033[1m" + _sgr(ICON_256) + ch + R
    if p.get("ask") is not None:
        lines[0][p["ask"]] = mark("?")
    icon = p.get("icon") or ""
    if icon:
        row = lines[p.get("icon_row", 0)]
        row[ROBOT_W - vwidth(icon):] = [mark(icon)]
    return "".join(lines[0]), "".join(lines[1])


def big_pose(seed, mood, mood_since, now, cols, family="alien", color=None, icon="",
             tick_len=1):
    """The two-row creature (big and tall): robot_pose for the robot
    family, the half-block pose for the rest. Every pose carries "kind"
    and its box width "w"."""
    if creature_family(family) == "robot":
        return robot_pose(seed, mood, mood_since, now, cols, color, icon, tick_len)
    return pose(seed, mood, mood_since, now, cols, family, color, icon, tick_len)


def render_big(p, rule_top=False):
    """(upper, lower) cell strings for a big_pose() pose, each p["w"] wide."""
    if p.get("kind") == "robot":
        return render_robot(p, rule_top)
    return render_box(p, rule_top)


# ── excursions: now and then the creature explores the rest of the bar ──
EXCURSION_KINDS = ("stretch", "peek", "crawl", "downstairs", "hang")
_EXCURSION_PICK = EXCURSION_KINDS + ("downstairs",)   # the bottom line twice as often
EXCURSION_S = {"stretch": (4, 5), "peek": (6, 12), "crawl": (10, 20),
               "downstairs": (12, 20), "hang": (6, 12)}  # seconds, low–high
EXCURSION_BUCKET_S = 600  # one excursion per 10 minutes …
EXCURSION_OFFSET = (150, 450)  # … starting this far in: 5–15 min apart
EXCURSION_MOODS = ("calm", "idle", "yours")


def excursion_plan(seed, bucket):
    """The excursion of 10-minute bucket `bucket`: {"kind", "start" (epoch
    seconds), "dur" (seconds), "sit" (downstairs sits on the cost field)},
    from (seed, bucket) alone."""
    rand = _mulberry32((int(seed) ^ (int(bucket) * 0x9E3779B1) ^ 0xE5C) & _M32)
    lo, hi = EXCURSION_OFFSET
    start = int(bucket) * EXCURSION_BUCKET_S + lo + int(rand() * (hi - lo))
    kind = _EXCURSION_PICK[int(rand() * len(_EXCURSION_PICK))]
    a, b = EXCURSION_S[kind]
    return {"kind": kind, "start": start, "dur": a + int(rand() * (b - a + 1)),
            "sit": rand() < 0.5}


def excursion_at(seed, now, tick_len=1):
    """The excursion on at `now`, or None: excursion_plan plus "phase" (its
    frame, 0 …) and "n" (its length in frames, at least 1). Frames are
    ticks of `tick_len` seconds, the first one the first tick to start
    inside it, so a long tick still shows every excursion."""
    tl = max(int(tick_len), 1)
    tick = int(now) // tl
    plan = excursion_plan(seed, tick * tl // EXCURSION_BUCKET_S)
    first = -(-plan["start"] // tl)
    n = max(plan["dur"] // tl, 1)
    if not first <= tick < first + n:
        return None
    return dict(plan, phase=tick - first, n=n)


def _double(cv):
    return [[v for v in row for _ in (0, 1)] for row in cv]


def _half_again(cv):  # one and a half times as wide: every other column twice
    return [[v for c, v in enumerate(row) for _ in range(1 + c % 2)] for row in cv]


def _peeking(cv, keep=3):
    """Only what shows round a corner: the head rows (the first `keep`)
    up to and including the first eye (and the arm beside it); the legs
    are hidden."""
    w = len(cv[0])
    eyes = [c for c in range(w) if any(cv[r][c] in ("e", "x") for r in range(len(cv)))]
    if eyes:
        cut = eyes[0]
        while cut + 1 in eyes:
            cut += 1
        cut += 1  # the rim right of the eye
    else:  # eyes shut this frame: the first few columns
        s = _span(_merge(_merge(cv[0], cv[1]), cv[2]))
        cut = (s[0] if s else 0) + 3
    return ([row[:cut + 1] + [None] * (w - cut - 1) for row in cv[:keep]] +
            [[None] * w for _ in range(len(cv) - keep)])


def _sprite(rows, row):
    """{"rows": cell rows trimmed to the columns they draw in, "off": the
    first kept column, "w", "row": 0 row 1 / 1 row 2 (its top row)}."""
    used = [c for c in range(len(rows[0])) if any(r[c] is not None for r in rows)]
    if not used:
        return None
    a, b = used[0], used[-1] + 1
    return {"rows": [r[a:b] for r in rows], "off": a, "w": b - a, "row": row}


def _sprites(size, p):
    """The creature of pose `p` as the excursions draw it: "home" (as on
    the rule), "half" / "wide" (stretched), "peek", "crawl" (row 1),
    "down" (row 2) and "hang" (upside down)."""
    if size == "tiny":
        def cells(dots):
            if len(dots[0]) % 2:
                dots = [row + [None] for row in dots]
            return [[None if ch is None else _sgr(p["body"]) + ch + R
                     for ch in braille(dots)]]
        cv = p["dots"]
        body = cells(cv)
        return {"home": _sprite(body, 0), "crawl": _sprite(body, 0),
                "down": _sprite(body, 1), "half": _sprite(cells(_half_again(cv)), 0),
                "wide": _sprite(cells(_double(cv)), 0), "peek": _sprite(cells(_peeking(cv)), 0),
                "hang": _sprite(cells(cv[::-1]), 1)}
    if p.get("kind") == "robot":
        def cells(dots):  # one braille cell row per 4 dot rows
            if len(dots[0]) % 2:
                dots = [row + [None] for row in dots]
            return [[None if ch is None else _sgr(p["body"]) + ch + R
                     for ch in braille(dots[r:r + 4])] for r in range(0, len(dots), 4)]
        cv = p["dots"]
        flat = [_merge(cv[r], cv[r + 4]) for r in range(4)]  # both halves on one text row
        return {"home": _sprite(cells(cv), 0), "crawl": _sprite(cells(flat), 0),
                "down": _sprite(cells(flat), 1), "half": _sprite(cells(_half_again(cv)), 0),
                "wide": _sprite(cells(_double(cv)), 0), "peek": _sprite(cells(_peeking(cv, 4)), 0),
                "hang": _sprite(cells(cv[::-1]), 0)}

    def cells(cv):
        return [[_half_cell(cv[2 * r][c], cv[2 * r + 1][c], p) for c in range(len(cv[0]))]
                for r in range(len(cv) // 2)]
    cv = p["canvas"]
    flat = cells([_merge(cv[0], cv[1]), _merge(cv[2], cv[3])])
    return {"home": _sprite(cells(cv), 0), "crawl": _sprite(flat, 0), "down": _sprite(flat, 1),
            "half": _sprite(cells(_half_again(cv)), 0), "wide": _sprite(cells(_double(cv)), 0),
            "peek": _sprite(cells(_peeking(cv)), 0), "hang": _sprite(cells(cv[::-1]), 0)}


def _lerp(a, b, f):
    return a + int(round((b - a) * min(max(f, 0.0), 1.0)))


def _put(s, x, geo):
    """Overlays for sprite `s` with its first column at x, kept off the
    leads and the corners."""
    x = max(2, min(x, geo["cols"] - 1 - s["w"]))
    return [(s["row"] + i, x, cells) for i, cells in enumerate(s["rows"])]


def _corner_x(s, geo):  # right up against the corner
    return geo["cols"] - 1 - s["w"]


# Each excursion is a pure frame function: (sprites, phase, n frames,
# geometry, sit) -> overlays [(row 0/1, column, cells)]. Geometry: "cols",
# "home" / "back" (the body's first column on the rule when it leaves and
# when it is due back), "rule2" (row 2's first free rule column), "seat"
# ((column, width) of row 2's duration/cost field, or None).
def _ex_stretch(sp, phase, n, geo, sit):
    # 1 frame growing, 2–3 at double width, then (n >= 4) one shrinking
    ends = n >= 3 and (phase == 0 or (n >= 4 and phase == n - 1))
    s = sp["half" if ends else "wide"]
    return _put(s, min(geo["home"], _corner_x(s, geo)), geo)


def _ex_peek(sp, phase, n, geo, sit):
    f, home = (phase + 0.5) / n, sp["home"]
    xc = _corner_x(home, geo)
    if f < 0.25:
        return _put(home, _lerp(geo["home"], xc, f / 0.25), geo)
    if f < 0.4:
        return []  # behind the corner
    if f < 0.85:
        return _put(sp["peek"], _corner_x(sp["peek"], geo), geo)
    return _put(home, _lerp(xc, geo["back"], (f - 0.85) / 0.15), geo)


def _ex_crawl(sp, phase, n, geo, sit):
    f, s = (phase + 0.5) / n, sp["crawl"]
    if f < 0.4:
        return _put(s, _lerp(geo["home"], 2, f / 0.4), geo)
    if f < 0.6:
        return _put(s, 2, geo)  # at the far end, by the lead
    return _put(s, _lerp(2, geo["back"], (f - 0.6) / 0.4), geo)


def _ex_downstairs(sp, phase, n, geo, sit):
    f, home, down = (phase + 0.5) / n, sp["home"], sp["down"]
    xc, xd = _corner_x(home, geo), _corner_x(down, geo)
    if f < 0.15:
        return _put(home, _lerp(geo["home"], xc, f / 0.15), geo)
    if f >= 0.85:
        return _put(home, _lerp(xc, geo["back"], (f - 0.85) / 0.15), geo)
    if f < 0.25:
        return _put(down, xd, geo)
    if sit and geo["seat"]:
        col, w = geo["seat"]
        seat = col + (w - down["w"]) // 2
        if f < 0.45:
            return _put(down, _lerp(xd, seat, (f - 0.25) / 0.2), geo)
        if f < 0.7:
            return _put(down, seat, geo)
        return _put(down, _lerp(seat, xd, (f - 0.7) / 0.15), geo)
    far = min(max(geo["rule2"], 2), xd)  # the left end of row 2's free rule
    if f < 0.55:
        return _put(down, _lerp(xd, far, (f - 0.25) / 0.3), geo)
    return _put(down, _lerp(far, xd, (f - 0.55) / 0.3), geo)


def _ex_hang(sp, phase, n, geo, sit):
    f, home, hang = (phase + 0.5) / n, sp["home"], sp["hang"]
    xc = _corner_x(home, geo)
    if f < 0.2:
        return _put(home, _lerp(geo["home"], xc, f / 0.2), geo)
    if f < 0.85:
        return _put(hang, _corner_x(hang, geo) - phase % 2, geo)  # it swings
    return _put(home, _lerp(xc, geo["back"], (f - 0.85) / 0.15), geo)


EXCURSIONS = {"stretch": _ex_stretch, "peek": _ex_peek, "crawl": _ex_crawl,
              "downstairs": _ex_downstairs, "hang": _ex_hang}


def _seat(row2):
    """(column, width) of row 2's duration/cost field ("$…" or "T:…"), or
    None."""
    texts = [t for _, t in split_cells(row2)[0]]
    plain = "".join(t or "\0" for t in texts)
    m = re.search(r"\$\d[\d.]*|\b\d+[hm]\b", plain)
    return (m.start(), m.end() - m.start()) if m else None


def excursion_rows(size, row1, row2, cols, frame_on, alien_pct, now, pres, look):
    """(row 1, row 2) with the creature out on an excursion, or None when
    none is on: excursions off (RETRO_HUD_EXCURSIONS=0), size not tiny or
    big, no creature (frame or alien off, a short rule), a mood other than
    calm, idle or yours, or a bubble or icon to show (it stays home while
    it has something to say). The rows are the plain frame with the
    creature laid over their cells; nothing moves."""
    if os.environ.get("RETRO_HUD_EXCURSIONS", "1").strip() == "0" or \
            size not in ("tiny", "big") or not frame_on or alien_pct is None:
        return None
    mood, mood_since, icon, bubble = _creature_mood(alien_pct, pres)
    mood = mood if mood in CREATURE_SPEEDS else "calm"
    if mood not in EXCURSION_MOODS or icon or bubble:
        return None
    tl = tick_s()
    ex = excursion_at(look["seed"], now, tl)
    if ex is None:
        return None
    if size == "tiny":
        start, track = vislen(row1) + 1, cols - vislen(row1) - 2
        if track < TINY_MIN_TRACK:
            return None
        def at(t):
            return tiny_pose(look["seed"], mood, mood_since, t, track, look["family"],
                             look["color"], "", tl)
    else:
        start = max(vislen(row1), vislen(row2)) + 1
        track = cols - 1 - start
        if track < CREATURE_MIN_TRACK:
            return None
        def at(t):
            return big_pose(look["seed"], mood, mood_since, t, track, look["family"],
                            look["color"], "", tl)
    sp = _sprites(size, at(now))
    if None in sp.values():
        return None
    left = (int(now) // tl - ex["phase"]) * tl  # its first frame
    rows = [_frame(row1, cols, "┐", True), _frame(row2, cols, "┘", True)]
    geo = {"cols": cols, "rule2": vislen(row2) + 1, "seat": _seat(rows[1]),
           "home": start + at(left)["pos"] + sp["home"]["off"],
           "back": start + at(left + ex["n"] * tl)["pos"] + sp["home"]["off"]}
    for r, col, cells in EXCURSIONS[ex["kind"]](sp, ex["phase"], ex["n"], geo, ex["sit"]):
        rows[r] = overlay(rows[r], col, cells)
    return rows[0], rows[1]


# ── row assembly ──
def _join(prefix, segs):
    return prefix + SEP.join(s for s in segs if s)


def pick_mood(gauge_pct, state):
    """Mood for this refresh: red-zone gauge → error → agitated gauge →
    what the agent is doing → calm."""
    if gauge_pct >= RED_PCT:
        return "red"
    if state == "error":
        return "error"
    if gauge_pct >= WARN_PCT:
        return "agitated"
    if state in ("needs", "working", "yours", "idle", "asleep"):
        return state
    return "calm"


def _place_bubble(pos, span, text, moving_right):
    """(side, text) for a bubble beside a sprite at `pos` on a `span` rule:
    side is 1 (after the sprite), -1 (before it) or 0 (no room)."""
    room = {1: span - pos, -1: pos}  # rule cells free on each side
    need = 1 + vwidth(text)          # the ╴ glyph + text
    for side in ((1, -1) if moving_right else (-1, 1)):
        if room[side] >= need:
            return side, text
    side = 1 if room[1] >= room[-1] else -1
    if room[side] < 3:  # glyph + 2 chars, or nothing
        return 0, ""
    fit = room[side] - 1
    if fit >= 6:
        return side, trunc(text, fit)
    out = ""  # too tight for a ".." suffix: a clean cut reads better
    for ch in text:
        if vwidth(out + ch) > fit:
            break
        out += ch
    return (side, out) if out else (0, "")


def _frame(row, cols, corner, frame_on, alien_pct=None, now=0, pres=None,
           action=None):
    """Pad with a dim rule and close the frame at the right edge.

    When alien_pct is given (and the rule is long enough), a text-art
    alien patrols the rule: it ping-pongs along it, blinking each 10s
    tick, walks faster as the worst gauge climbs, and its face and
    color escalate green → amber → red with that gauge's zone.

    `pres` (agent presence) overrides the gauge-only behaviour with
    {"mood", "bubble", "since", "sprite"}: the mood picks frames, color
    and speed from SPRITES / MOOD_SPEEDS / MOOD_COLORS, and a bubble is
    drawn on the rule beside the sprite, in its travel direction. The
    bubble takes rule cells, never adds any: the frame math is unchanged.

    `action` (from make_action) wraps the sprite, not its bubble, in the
    retro-hud://card link; links are invisible, so nothing moves.
    """
    gap = cols - vislen(row)
    if not frame_on or gap < 2:
        return row
    track = gap - 2  # rule cells between the leading space and the corner
    fill = "─" * track
    if alien_pct is not None and track >= 10:
        tick = now // 10  # struts every 10s; visible with a short refreshInterval
        if pres is None:
            mood = 0 if alien_pct < WARN_PCT else (1 if alien_pct < RED_PCT else 2)
            sprite = ALIEN_FRAMES[mood][tick % 2]
            color = (NEON_GREEN, NEON_ORG, NEON_RED)[mood]
            speed, bubble = ALIEN_SPEEDS[mood], ""
        else:
            mood = pres.get("mood") if pres.get("mood") in MOOD_SPEEDS else "calm"
            frames = SPRITES.get(pres.get("sprite"), SPRITES["alien"])[mood]
            sprite, color = frames[tick % 2], MOOD_COLORS[mood]
            since = int(pres.get("since") or 0)
            speed = MOOD_SPEEDS[mood]
            if mood == "yours" and now - since < WAVE_S:
                speed = 0
            if speed == 0:  # park where a calm cruise stood when the mood began
                tick = since // 10
                speed = 1
            bubble = pres.get("bubble") or ""
        span = track - len(sprite)
        t = tick * speed % (2 * span)
        pos = t if t <= span else 2 * span - t
        side, bubble = _place_bubble(pos, span, bubble, t < span) if bubble else (0, "")
        bw = 1 + vwidth(bubble) if side else 0
        left = "─" * (pos - bw if side == -1 else pos)
        right = "─" * (span - pos - bw if side == 1 else span - pos)
        if side == -1:
            left += R + BUBBLE + bubble + R + RULE + "╶"
        mid = R + color + (action("card", sprite) if action else sprite) + R + RULE
        if side == 1:
            mid += "╴" + R + BUBBLE + bubble + R + RULE
        fill = left + mid + right
    return "{} {}{}{}{}{}{}".format(row, RULE, fill, R, NEON_GREEN, corner, R)


def _boxed(row, cols, corner, col, box, box_w, bubble="", right=True):
    """`row` closed by the rule and `corner` as _frame does, with `box`
    (visible width box_w) at absolute column `col` and, when it fits, a
    bubble on the rule beside it, in the travel direction."""
    lpad = col - vislen(row) - 1
    rpad = cols - 1 - col - box_w
    side, bubble = _place_bubble(lpad, lpad + rpad, bubble, right) if bubble else (0, "")
    bw = 1 + vwidth(bubble) if side else 0
    left = "─" * (lpad - bw if side == -1 else lpad)
    rest = "─" * (rpad - bw if side == 1 else rpad)
    if side == -1:
        left += R + BUBBLE + bubble + R + RULE + "╶"
    mid = R + box + RULE
    if side == 1:
        mid += "╴" + R + BUBBLE + bubble + R + RULE
    return "{} {}{}{}{}{}{}".format(row, RULE, left + mid + rest, R, NEON_GREEN, corner, R)


def _creature_mood(alien_pct, pres):
    """(mood, mood_since, icon, bubble) for the creature this refresh."""
    if pres is None:  # gauge-only: calm, agitated or red, steady poses
        mood = "calm" if alien_pct < WARN_PCT else ("agitated" if alien_pct < RED_PCT else "red")
        return mood, None, "", ""
    icon = pres.get("icon") or ""
    return (pres.get("mood"), _num_or_none(pres.get("mood_since")),
            icon if _icon_ok(icon) else "", pres.get("bubble") or "")


def _frame_tiny(row, cols, frame_on, alien_pct, now, pres, look, action=None):
    """Row 1 with the tiny braille creature in a fixed 7-cell box on the
    rule and its bubble beside it (as the 2.x alien's). No creature (alien
    off, frame off, a rule shorter than TINY_MIN_TRACK): the plain rule."""
    track = cols - vislen(row) - 2
    if not frame_on or alien_pct is None or track < TINY_MIN_TRACK:
        return _frame(row, cols, "┐", frame_on)
    mood, mood_since, icon, bubble = _creature_mood(alien_pct, pres)
    p = tiny_pose(look["seed"], mood, mood_since, now, track, look["family"],
                  look["color"], icon, tick_s())
    box = render_tiny(p)
    if action:
        box = action("card", box)
    col = vislen(row) + 1 + p["pos"]
    return _boxed(row, cols, "┐", col, box, TINY_W, bubble, p["right"])


def _frame_big(row1, row2, cols, frame_on, alien_pct, now, pres, look, action=None):
    """(row 1, row 2) with the half-block creature straddling them: its
    upper two pixel rows replace rule cells on row 1, its lower two the
    cells below them on row 2. It walks the rule the two rows share (row
    2's free rule starts after its own last segment) in a fixed 13-cell
    box; the bubble and an event icon stay on row 1. With no shared rule
    of CREATURE_MIN_TRACK cells both rows are the plain frame."""
    plain = (_frame(row1, cols, "┐", frame_on), _frame(row2, cols, "┘", frame_on))
    start = max(vislen(row1), vislen(row2)) + 1  # first rule column on both rows
    track = cols - 1 - start
    if not frame_on or alien_pct is None or track < CREATURE_MIN_TRACK:
        return plain
    mood, mood_since, icon, bubble = _creature_mood(alien_pct, pres)
    p = big_pose(look["seed"], mood, mood_since, now, track, look["family"], look["color"],
                 icon, tick_s())
    top, bottom = render_big(p, rule_top=True)
    if action:
        top, bottom = action("card", top), action("card", bottom)
    col, bw = start + p["pos"], p["w"]
    return (_boxed(row1, cols, "┐", col, top, bw, bubble, p["right"]),
            _boxed(row2, cols, "┘", col, bottom, bw))


def _frame_creature(row, cols, frame_on, alien_pct, now, pres, look, action=None):
    """(head line, row 1) with the pixel creature.

    Row 1 is `row` closed by the rule and corner exactly as _frame does;
    the creature's lower half replaces 13 rule cells, its upper half sits
    in the same 13 columns of the head line, which holds nothing else but
    the bubble (beside the box, in the travel direction). No creature
    (alien off, frame off, a rule shorter than CREATURE_MIN_TRACK): the
    head line is a bare SGR reset, never an empty string, so the HUD keeps
    its three lines.

    `pres` is presence() or None (the gauge-only creature: calm, agitated
    or red by alien_pct, steady poses). `look` is {"seed", "family",
    "color"}. `action` (from make_action) links both halves of the box,
    never the bubble, to retro-hud://card.
    """
    gap = cols - vislen(row)
    track = gap - 2
    if not frame_on or alien_pct is None or track < CREATURE_MIN_TRACK:
        return R, _frame(row, cols, "┐", frame_on)
    if pres is None:
        mood = "calm" if alien_pct < WARN_PCT else ("agitated" if alien_pct < RED_PCT else "red")
        mood_since, icon, bubble = None, "", ""
    else:
        mood, mood_since = pres.get("mood"), _num_or_none(pres.get("mood_since"))
        icon, bubble = pres.get("icon") or "", pres.get("bubble") or ""
    p = big_pose(look["seed"], mood, mood_since, now, track, look["family"], look["color"],
                 icon if _icon_ok(icon) else "", tick_s())
    head13, rule13 = render_big(p)
    if action:
        head13, rule13 = action("card", head13), action("card", rule13)
    bw = p["w"]                  # 13 cells, or the robot's 9
    pos, span = p["pos"], track - bw
    fill = "─" * pos + R + rule13 + RULE + "─" * (span - pos)
    row1 = "{} {}{}{}{}{}{}".format(row, RULE, fill, R, NEON_GREEN, "┐", R)
    col = vislen(row) + 1 + pos  # the box's first column, on both lines
    room = cols - col - bw       # head-line cells right of the box
    side, bubble = _place_bubble(col, col + room, bubble, p["right"]) if bubble else (0, "")
    bw = 1 + vwidth(bubble) if side else 0
    if side == -1:
        head = " " * (col - bw) + BUBBLE + bubble + R + " " + head13
    else:
        head = " " * col + head13
        if side == 1:
            head += " " + BUBBLE + bubble + R
    return R + head, row1


def creature_look(data, pres):
    """{"seed", "family", "color"} for this session. The state file's
    `seed` / `sprite` win over RETRO_HUD_CREATURE_SEED / RETRO_HUD_SPRITE;
    without presence the state file is only peeked at, never written."""
    sid = data.get("session_id")
    sid = sid if isinstance(sid, str) and _SID_RE.fullmatch(sid) else ""
    if pres is not None:
        st_seed, sprite = pres.get("seed"), pres.get("sprite")
    else:
        prev = {}
        d = cache_dir(create=False) if sid else ""
        if d:
            prev = _read_json(os.path.join(d, sid + ".state.json"))
        st_seed, sprite = prev.get("seed"), prev.get("sprite")
        if sprite not in SPRITES and sprite not in FAMILIES:
            sprite = os.environ.get("RETRO_HUD_SPRITE")
    seed = creature_seed(st_seed, os.environ.get("RETRO_HUD_CREATURE_SEED", ""), sid)
    # color None: the size's own default (seeded, or the tiny alien's green)
    return {"seed": seed, "family": creature_family(sprite),
            "color": pinned_color(os.environ.get("RETRO_HUD_CREATURE_COLOR", ""))}


SIZES = ("tiny", "big", "tall")


def creature_size(data=None):
    """"tiny" (the default), "big", "tall" or "off". RETRO_HUD_CREATURE=0
    is off whatever else says; otherwise the state file's `size` (set from
    the click menu) wins over the environment."""
    env = os.environ.get("RETRO_HUD_CREATURE", "").strip().lower()
    if env == "0":
        return "off"
    size = env if env in SIZES else "tiny"
    sid = data.get("session_id") if isinstance(data, dict) else None
    if isinstance(sid, str) and _SID_RE.fullmatch(sid):
        d = cache_dir(create=False)
        if d:
            st = _read_json(os.path.join(d, sid + ".state.json")).get("size")
            if st in SIZES:
                size = st
    return size


def tick_s():
    """Seconds per animation frame: RETRO_HUD_TICK_S, a positive integer
    (default 1). The frame index is now // tick_s()."""
    v = os.environ.get("RETRO_HUD_TICK_S", "").strip()
    return int(v) if v.isdigit() and int(v) > 0 else 1


def render(data, cols, now, _edges=True):
    """Return [row1, row2] sized to cols, or [head line, row1, row2]
    with the tall creature (RETRO_HUD_CREATURE=tall). `_edges` False:
    the ◈ / ⌂ buttons as segments, not at the right edge (the fallback
    when reserving their cell leaves the frame no room)."""
    global _EMOJI_W
    frame_on = os.environ.get("RETRO_HUD_FRAME", "1") != "0"
    size = creature_size(data)
    creature = size != "off"
    cd_pct = num(os.environ.get("RETRO_HUD_COUNTDOWN_PCT"), WARN_PCT)
    emoji_mode = os.environ.get("RETRO_HUD_EMOJI", "2")
    _EMOJI_W = 1 if emoji_mode == "1" else 2
    ctx_tok_mode = os.environ.get("RETRO_HUD_CTX_TOKENS", "auto")

    # ── extract fields ──
    cwd = str(dig(data, "workspace", "current_dir") or data.get("cwd") or "~")
    model = str(dig(data, "model", "display_name") or dig(data, "model", "id") or "---")
    effort = str(dig(data, "effort", "level") or "")
    vim_mode = str(dig(data, "vim", "mode") or "")
    session_name = str(data.get("session_name") or "")

    ctx_pct = dig(data, "context_window", "used_percentage")
    ctx_tok = num(dig(data, "context_window", "total_input_tokens"))
    win_size = num(dig(data, "context_window", "context_window_size"))
    if ctx_pct is None and win_size:
        ctx_pct = ctx_tok * 100 // win_size
    ctx_pct = num(ctx_pct)

    usage = dig(data, "context_window", "current_usage") or {}
    cache_read = num(usage.get("cache_read_input_tokens"))
    cache_denom = cache_read + num(usage.get("input_tokens")) + \
        num(usage.get("cache_creation_input_tokens"))

    cost = 0.0
    try:
        cost = float(dig(data, "cost", "total_cost_usd") or 0)
    except (TypeError, ValueError):
        pass
    dur_ms = num(dig(data, "cost", "total_duration_ms"))
    lines_add = num(dig(data, "cost", "total_lines_added"))
    lines_del = num(dig(data, "cost", "total_lines_removed"))

    agent_name = str(dig(data, "agent", "name") or "")
    worktree = str(dig(data, "worktree", "name") or dig(data, "workspace", "git_worktree") or "")

    has_rl = isinstance(data.get("rate_limits"), dict)
    rl5_pct = num(dig(data, "rate_limits", "five_hour", "used_percentage"))
    rl7_pct = num(dig(data, "rate_limits", "seven_day", "used_percentage"))
    rl5_reset = num(dig(data, "rate_limits", "five_hour", "resets_at"))
    rl7_reset = num(dig(data, "rate_limits", "seven_day", "resets_at"))
    rl5_left = max(rl5_reset - now, 0)
    rl7_left = max(rl7_reset - now, 0)

    pr_num = num(dig(data, "pr", "number"))
    pr_url = str(dig(data, "pr", "url") or "")
    pr_state = str(dig(data, "pr", "review_state") or "pending")

    branch = str(data.get("_branch_override") or "") or git_branch(cwd)
    gh_url = repo_url(data, cwd, branch) if branch else ""
    dir_name = os.path.basename(cwd.rstrip(os.sep)) or cwd
    action = make_action()

    # ── gauge widths scale with the terminal ──
    ctx_len = clamp(cols // 20, 4, 10)
    rl_len = clamp(cols // 40, 3, 6)

    # ── duration (rounded hard: the field must not jitter) ──
    dur_str = fmt_short_dur(dur_ms)

    # ═══ ROW 1 ═══
    def model_seg(name):
        inner = MODEL_TXT + action("model", name) + R
        if effort in EFFORT_GLYPHS:
            inner += " " + EFFORT_COLORS[effort] + action(
                "effort", EFFORT_GLYPHS[effort], "&cur=" + effort) + R
        return "{}[{} {} {}]{}".format(MODEL_BOX, R, inner, MODEL_BOX, R)

    def dir_seg(name):
        icon = "\U0001F4C2 " if emoji_mode != "0" else ""
        return NEON_WHT + icon + name + R

    def branch_seg(name):
        return "{} ⎇ {} {}".format(BRANCH_BADGE, link(gh_url, name), R)

    def pr_seg():
        color, glyph = PR_STATE.get(pr_state, PR_STATE["pending"])
        return color + link(pr_url, "#{}{}".format(pr_num, glyph)) + R

    def vim_seg():
        return VIM_COLORS.get(vim_mode, NEON_CYAN) + "[" + vim_mode[0] + "]" + R

    # RETRO_HUD_SESSION_NAME: 1 (default) the session's name, icon just the ◈
    # (an auto-generated name takes space), 0 nothing; the ◈ stays the
    # agent menu's link either way
    sid_for_cache = data.get("session_id") if isinstance(data.get("session_id"), str) else ""
    name_mode = os.environ.get("RETRO_HUD_SESSION_NAME", "1").strip().lower()
    # 1 (default) the ◈ name segment, the agent menu's link; 0 (or the old
    # "icon") nothing: the creature's cloud reaches that menu too

    def session_seg(name):  # the name beside the creature is the agent menu's link
        return DIM + action("agent", "◈ " + name) + R

    # The home and return buttons stand OUTSIDE the frame at the far right, in
    # the one column the frame always leaves free (so the end bars line up
    # whatever shows): away from home, ⌂ (RETRO_HUD_HOME_URL) right after the ┐; on
    # the home session (RETRO_HUD_AT_HOME=1) after a ⌂ click, ↩
    # (RETRO_HUD_BACK_URL) past the ┘ on row 2, which goes back to the session
    # you came from (the handler keeps that in <cache>/home-from, written on
    # every arrival at home it makes, cleared by ↩, ignored after 12 h); started
    # on home, neither. The other cell of the column is a plain blank.
    # With the frame off the button is an ordinary segment.
    home_url = _clean_url(os.environ.get("RETRO_HUD_HOME_URL", ""))
    back_url = _clean_url(os.environ.get("RETRO_HUD_BACK_URL", ""))
    # a retro-hud:// home or back link carries the pane and socket like the other
    # actions, so the handler reaches the right tmux server; other schemes as given
    _q = action_query()
    if _q:
        home_url = home_url + "?" + _q if home_url.startswith("retro-hud://") and "?" not in home_url else home_url
        back_url = back_url + "?" + _q if back_url.startswith("retro-hud://") and "?" not in back_url else back_url
    at_home = os.environ.get("RETRO_HUD_AT_HOME", "").strip() == "1"
    button_url, button = "", ""
    if home_url and not at_home:
        button_url, button = home_url, "⌂"
    elif at_home and back_url and _home_from():
        button_url, button = back_url, "↩"
    home_seg = NEON_GREEN + link(button_url, button) + R if button else ""
    edge_w = 1 if frame_on and _edges and home_url else 0
    full_cols, cols = cols, cols - edge_w
    frame_room = 2 if frame_on else 0   # the frame's lead space and corner: a row must leave them

    # Auto-generated session names run long — cap them before layout.
    t_model, t_dir, t_branch = model, dir_name, branch
    t_session = trunc(session_name, 28)
    show_pr, show_vim = pr_num > 0, bool(vim_mode)
    show_session = bool(session_name) and name_mode not in ("0", "icon")

    for step in range(9):
        segs = [model_seg(t_model), dir_seg(t_dir)]
        if t_branch:
            segs.append(branch_seg(t_branch))
        if show_pr:
            segs.append(pr_seg())
        if show_vim:
            segs.append(vim_seg())
        if show_session:
            segs.append(session_seg(t_session))
        row1 = _join(NEON_GREEN + "┌─" + R, segs)
        if vislen(row1) <= cols - frame_room:
            break
        if step == 0:
            show_session = False
        elif step == 1:
            show_vim = False
        elif step == 2:
            t_branch = trunc(branch, 16)
            t_dir = trunc(dir_name, 14)
        elif step == 3:
            show_pr = False
        elif step == 4:
            t_branch = trunc(branch, 8)
            t_dir = trunc(dir_name, 8)
        elif step == 5:
            t_branch = ""
        elif step == 6:
            t_model = trunc(model, 12)
        else:
            t_dir = trunc(dir_name, max(cols - vislen(_join("xx", [model_seg(t_model)])) - 7, 3))

    # ═══ ROW 2 ═══
    def ctx_seg(tok_mode):
        # tok_mode: 2 = "42% 87.3K/200K", 1 = "42% 87.3K", 0 = "42%"
        # "auto" shows tokens only from the amber zone up — that's when
        # remaining headroom becomes an actionable number.
        if ctx_tok_mode == "never" or \
                (ctx_tok_mode == "auto" and clamp(ctx_pct, 0, 999) < WARN_PCT):
            tok_mode = 0
        c = value_color(clamp(ctx_pct, 0, 100))
        s = action("ctx", "{} {}{}%{}".format(
            ctx_gauge(ctx_pct, ctx_len), c, clamp(ctx_pct, 0, 999), R))
        if tok_mode and ctx_tok:
            t = fmt_tok(ctx_tok)
            if tok_mode == 2 and win_size:
                t += "/" + fmt_win(win_size)
            s += " " + NEON_WHT + t + R
        return s

    rl_mode = os.environ.get("RETRO_HUD_RL_MODE", "cycle")
    if rl_mode not in ("cycle", "pct", "time", "both"):
        rl_mode = "cycle"
    def time_phase(pct):
        period = RED_CYCLE_S if pct >= RED_PCT else CYCLE_S
        return rl_mode == "time" or (rl_mode == "cycle" and (now // period) % 2 == 1)

    def rl_label(pct, left, reset, rich, mirror=False):
        # Escalation ladder: calm → cycle; ≥ cd_pct (the amber zone) →
        # the pinned "81% · 3d". Once a gauge is in warning it stops
        # rotating for good — the % and the countdown are the last two
        # things row 2 gives up, so neither flickers away under you.
        # `mirror` flips the 5h side to "3d · 81%" so that on both halves
        # of the gauge the % is the token touching the bar.
        # Returns (label, flex): labels stay tight, and in cycle mode the
        # gauge stretches by `flex` cells — the width the other phase's
        # label would need — so the flip never moves anything.
        pct_lbl = "{}%".format(clamp(pct, 0, 999))
        if not reset:
            return pct_lbl, 0
        cd_lbl = fmt_countdown(left)
        if rich and (pct >= cd_pct or rl_mode == "both"):
            return " · ".join((cd_lbl, pct_lbl) if mirror else (pct_lbl, cd_lbl)), 0
        tp = time_phase(pct)
        if rl_mode != "cycle":
            return (cd_lbl if tp else pct_lbl), 0
        shown, other = (cd_lbl, pct_lbl) if tp else (pct_lbl, cd_lbl)
        return shown, max(vwidth(other) - vwidth(shown), 0)

    def rl_seg(rich):
        l5, flex5 = rl_label(rl5_pct, rl5_left, rl5_reset, rich, mirror=True)
        l7, flex7 = rl_label(rl7_pct, rl7_left, rl7_reset, rich)
        return action("usage", rate_mirror(rl5_pct, rl7_pct, rl_len + flex5,
                                           rl_len + flex7, l5, l7))

    def lines_seg():
        return action("diff", "{}+{}{}{}/{}{}-{}{}".format(
            NEON_GREEN, lines_add, R, DIM, R, NEON_RED, lines_del, R))

    def cache_seg():
        pct = cache_read * 100 // cache_denom
        return "{}cache{} {}{}%{}".format(DIM, R, NEON_CYAN, pct, R)

    def agent_seg():
        parts = []
        if agent_name:
            parts.append("{}▐█{} {}{}{}".format(NEON_CYAN, R, NEON_WHT, agent_name, R))
        if worktree:
            parts.append("{}⎇ {}{}".format(NEON_PINK, worktree, R))
        return " ".join(parts)

    # The jump-home link is one cell, never dropped by the ladder below: at the
    # right edge of row 2 (above), or a segment when the frame is off.
    cost_mode = os.environ.get("RETRO_HUD_COST_MODE", "cycle")
    if cost_mode not in ("cycle", "both"):
        cost_mode = "cycle"
    cost_str = fmt_short_cost(cost)

    def cost_seg(cycle):
        """Cost alone, or (cycle mode) duration ↔ cost in ONE field. Both are
        rounded hard (fmt_short_dur / fmt_short_cost), so their widths differ
        by a cell or two at most; no padding, so the spacing round the
        separators stays even. The narrow-terminal ladder passes
        cycle=False and shows the cost alone."""
        if not cycle:
            return NEON_YEL + action("cost", cost_str) + R
        if (now // CYCLE_S) % 2 == 1:
            return NEON_PINK + action("cost", dur_str) + R
        return NEON_YEL + action("cost", cost_str) + R

    show_lines = lines_add > 0 or lines_del > 0
    show_dur = True
    show_cache = cache_denom > 0 and cols >= 140
    show_agent = bool(agent_name or worktree)
    # ▣ N: the other Claude sessions the presence cache knows (RETRO_HUD_SESSIONS=1),
    # ⚑ M of them needing you; the link opens the handler's session list
    sessions_seg = ""
    if os.environ.get("RETRO_HUD_SESSIONS", "").strip() == "1":
        live, needing = other_sessions(sid_for_cache, now)
        if live:
            sessions_seg = NEON_CYAN + action("sessions", "▣ {}".format(live)) + R
            if needing:
                sessions_seg += " " + NEON_YEL + action("sessions", "⚑ {}".format(needing)) + R
    tok_mode, rl_rich = 2, True

    for step in range(8):
        segs = [ctx_seg(tok_mode)]
        if has_rl:
            segs.append(rl_seg(rl_rich))
        if show_lines:
            segs.append(lines_seg())
        if show_cache:
            segs.append(cache_seg())
        if show_dur and cost_mode == "both":
            segs.append(NEON_PINK + "T:" + dur_str + R)
        segs.append(cost_seg(show_dur and cost_mode == "cycle"))
        if show_agent:
            segs.append(agent_seg())
        if sessions_seg:
            segs.append(sessions_seg)
        if not edge_w:
            segs.append(home_seg)
        row2 = _join(NEON_GREEN + "└─" + R, segs)
        if vislen(row2) <= cols - frame_room:
            break
        if step == 0:
            show_cache = False
        elif step == 1:
            tok_mode = 1
        elif step == 2:
            show_lines = False
        elif step == 3:
            tok_mode = 0
        elif step == 4:
            show_agent = False
        elif step == 5:
            show_dur = False
        else:
            rl_rich = False

    alien_pct = pres = None
    if os.environ.get("RETRO_HUD_ALIEN", "1") != "0":
        limit_pct = max(clamp(rl5_pct, 0, 100), clamp(rl7_pct, 0, 100)) if has_rl else 0
        alien_pct = max(clamp(ctx_pct, 0, 100), limit_pct)
        try:
            pres = presence(data, now, alien_pct, clamp(ctx_pct, 0, 100),
                            limit_pct, round(cost, 2), creature)
        except Exception:  # presence is decoration: never cost the bar
            pres = None

    def assemble():
        if size == "tall":
            try:
                head, top = _frame_creature(row1, cols, frame_on, alien_pct, now, pres,
                                            creature_look(data, pres), action)
            except Exception:  # decoration again: a blank head line, a plain rule
                head, top = R, _frame(row1, cols, "┐", frame_on)
            return [head, top, _frame(row2, cols, "┘", frame_on)]
        look = out = None
        if size in ("tiny", "big"):
            try:
                look = creature_look(data, pres)
                out = excursion_rows(size, row1, row2, cols, frame_on, alien_pct, now, pres, look)
            except Exception:  # decoration: the creature stays home
                out = None
            if out:
                return list(out)
        if size == "big":
            try:
                return list(_frame_big(row1, row2, cols, frame_on, alien_pct, now, pres,
                                       look or creature_look(data, pres), action))
            except Exception:  # decoration: the plain frame
                return [_frame(row1, cols, "┐", frame_on), _frame(row2, cols, "┘", frame_on)]
        if size == "tiny":
            try:
                top = _frame_tiny(row1, cols, frame_on, alien_pct, now, pres,
                                  look or creature_look(data, pres), action)
            except Exception:  # decoration: the plain frame
                top = _frame(row1, cols, "┐", frame_on)
            return [top, _frame(row2, cols, "┘", frame_on)]
        return [_frame(row1, cols, "┐", frame_on, alien_pct, now, pres, action),
                _frame(row2, cols, "┘", frame_on)]

    rows = assemble()
    if edge_w and not all(_closed(r, c) for r, c in zip(rows[-2:], "┐┘")):
        return render(data, full_cols, now, _edges=False)   # no room: the ⌂ as a segment
    if edge_w:
        top = home_seg if button == "⌂" else " "            # the other cell: plain, no hidden link
        bottom = home_seg if button == "↩" else " "
        rows = [r + top if i == len(rows) - 2 else
                r + bottom if i == len(rows) - 1 else r
                for i, r in enumerate(rows)]
    return rows


def _clean_url(url):
    """Control characters stripped, so a URL can't break out of OSC 8."""
    return "".join(ch for ch in url if ch.isprintable()).strip()


HOME_FROM_MAX_S = 12 * 3600   # an older record is a stale one: no ↩ for it


def _home_from():
    """The session you came home from, if the handler recorded one in
    <cache>/home-from within the last HOME_FROM_MAX_S seconds (it writes
    the file on every arrival at home it makes and removes it when ↩ is
    used)."""
    d = cache_dir(create=False)
    if not d:
        return ""
    path = os.path.join(d, "home-from")
    try:
        if time.time() - os.path.getmtime(path) > HOME_FROM_MAX_S:
            return ""
        with open(path) as f:
            return f.read(256).strip()
    except OSError:
        return ""


def _closed(row, corner):
    return row.endswith(NEON_GREEN + corner + R)


# ── entry point ──
DEMO_DATA = {
    "model": {"display_name": "Fable 5"},
    "_branch_override": "main",
    "workspace": {"current_dir": "/home/ripley/projects/nostromo",
                  "repo": {"host": "github.com", "owner": "example",
                           "name": "ccstatusline_retro-hud"}},
    "session_name": "retro-hud-v2",
    "effort": {"level": "max"},
    "thinking": {"enabled": True},
    "vim": {"mode": "INSERT"},
    "agent": {"name": "reviewer"},
    "context_window": {"used_percentage": 72, "total_input_tokens": 144213,
                       "context_window_size": 200000,
                       "current_usage": {"input_tokens": 2900,
                                         "cache_read_input_tokens": 137300,
                                         "cache_creation_input_tokens": 4013,
                                         "output_tokens": 1150}},
    "cost": {"total_cost_usd": 3.21, "total_duration_ms": 5432100,
             "total_lines_added": 128, "total_lines_removed": 37},
    "pr": {"number": 42, "url": "https://github.com/example/ccstatusline_retro-hud/pull/42",
           "review_state": "approved"},
    "rate_limits": {"five_hour": {"used_percentage": 63},
                    "seven_day": {"used_percentage": 81}},
}


def main(argv):
    if "--version" in argv:
        print("retro-hud " + __version__)
        return 0
    if "--demo" in argv:
        data = dict(DEMO_DATA)
        now = int(time.time())
        data["rate_limits"]["five_hour"]["resets_at"] = now + 7200
        data["rate_limits"]["seven_day"]["resets_at"] = now + 259200
    else:
        try:
            data = json.load(sys.stdin)
            if not isinstance(data, dict):
                data = {}
        except (ValueError, OSError):
            data = {}
        now = int(time.time())

    cols = num(os.environ.get("RETRO_HUD_WIDTH")) or \
        shutil.get_terminal_size((100, 24)).columns
    # Claude Code draws the status line inside its prompt footer, which
    # pads 2 columns on each side (inline mode, as of Claude Code 2.1.309),
    # plus 2 × statusLine.padding if set. A row wider than that box is cut
    # with an ellipsis (see anthropics/claude-code#36417), so the default
    # margin is 4. Tune with RETRO_HUD_MARGIN if it still clips or gaps.
    cols = max(cols - num(os.environ.get("RETRO_HUD_MARGIN"), 4), 20)
    try:
        rows = render(data, cols, now)
    except Exception:  # never break the statusline — degrade gracefully
        model = dig(data, "model", "display_name") or "retro-hud"
        rows = ["{}┌─{}[ {}{}{} ]{}".format(NEON_GREEN, R, MODEL_TXT, model, R + MODEL_BOX, R),
                "{}└─{} {}(status degraded){}".format(NEON_GREEN, R, DIM, R)]
        try:
            tall = creature_size(data) == "tall"
        except Exception:
            tall = False
        if tall:
            rows.insert(0, R)  # three lines whatever happens: nothing jumps
    print("\n".join(rows), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
