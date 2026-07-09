#!/usr/bin/env python3
"""Claude Code statusLine — RETRO SCI-FI HUD

Two-row HUD with a full wireframe, zoned gauges, and width-aware
degradation. Reads the statusline JSON payload on stdin and prints
two ANSI rows sized to $COLUMNS.

Flags:
    --version   print version and exit
    --demo      render with sample data (no stdin needed)

Env toggles:
    RETRO_HUD_FRAME=0            disable the right-edge frame fill
    RETRO_HUD_COUNTDOWN_PCT=75   rate-limit % at which reset countdowns appear
    RETRO_HUD_RL_MODE=cycle      rate-limit labels: cycle (alternate % and
                                 time-to-reset every 30s), pct, time, or both
    RETRO_HUD_ALIEN=0            ground the alien that patrols the top rule

Rate-limit label escalation: below the countdown threshold the label
cycles (or is pinned by RETRO_HUD_RL_MODE); from the threshold it shows
"81% · 3d"; in the red zone (>=90%) it switches to time-to-reset only —
the gauge itself already shows the saturation. "both" mode opts out.
"""
__version__ = "2.3.0"

import json
import os
import re
import shutil
import sys
import time
import unicodedata

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

SEP = " " + NEON_CYAN + "//" + R + " "

_FULL = "█"
_FRAC = ["", "▏", "▎", "▍", "▌", "▋", "▊", "▉"]

EFFORT_GLYPHS = {"low": "·", "medium": "•", "high": "●",
                 "xhigh": "⬤", "max": "✦"}
EFFORT_COLORS = {"low": DIM, "medium": NEON_CYAN, "high": NEON_YEL,
                 "xhigh": NEON_ORG, "max": NEON_PINK}
PR_STATE = {"approved": (NEON_GREEN, "✓"), "pending": (NEON_YEL, "○"),
            "changes_requested": (NEON_RED, "✗"), "draft": (DIM, "◌")}
ALIEN_SPRITES = ("👾", "👽", "🛸")   # calm / agitated / red-zone mothership
ALIEN_SPEEDS = (1, 2, 4)             # rule-cells per 30s tick
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
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def vislen(s):
    return vwidth(strip_ansi(s))


def trunc(s, maxw):
    """Truncate to maxw visible columns, '..' suffix when cut."""
    if vwidth(s) <= maxw:
        return s
    if maxw <= 2:
        return s[:maxw]
    out, w = "", 0
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + cw > maxw - 2:
            break
        out += ch
        w += cw
    return out + ".."


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


def rate_mirror(pct_5h, pct_7d, bar_len, lbl_5h, lbl_7d):
    """5h gauge fills right-to-left, 7d left-to-right, meeting at center."""
    fc_5h = value_color(pct_5h) if pct_5h >= WARN_PCT else RL_5H_FC
    fc_7d = value_color(pct_7d) if pct_7d >= WARN_PCT else RL_7D_FC
    bg_5h = RL_5H_EC.replace("38;5;", "48;5;")
    bg_7d = RL_7D_EC.replace("38;5;", "48;5;")
    bg_fc_5h = fc_5h.replace("1;38;5;", "48;5;").replace("38;5;", "48;5;")
    p5, p7 = clamp(pct_5h, 0, 100), clamp(pct_7d, 0, 100)

    units = p5 * bar_len * 8 // 100
    full, frac = units // 8, units % 8
    empty = bar_len - full - (1 if frac else 0)
    left = "{}{}{} {}{}{}".format(fc_5h, lbl_5h, R, bg_5h, " " * empty, R)
    if frac:  # mirrored partial: bright bg, dark fg, inverted eighth-block
        left += "{}{}{}{}".format(bg_fc_5h, RL_5H_EC, _FRAC[8 - frac], R)
    left += "{}{}{}".format(fc_5h, _FULL * full, R)

    units = p7 * bar_len * 8 // 100
    full, frac = units // 8, units % 8
    empty = bar_len - full - (1 if frac else 0)
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


# ── row assembly ──
def _join(prefix, segs):
    return prefix + SEP.join(s for s in segs if s)


def _frame(row, cols, corner, frame_on, alien_pct=None, now=0):
    """Pad with a dim rule and close the frame at the right edge.

    When alien_pct is given (and the rule is long enough), an alien
    patrols the rule: it ping-pongs one cell per 30s tick, walks faster
    as the worst gauge climbs, and escalates 👾 → 👽 → 🛸 by zone.
    """
    gap = cols - vislen(row)
    if not frame_on or gap < 2:
        return row
    track = gap - 2  # rule cells between the leading space and the corner
    fill = "─" * track
    if alien_pct is not None and track >= 8:
        mood = 0 if alien_pct < WARN_PCT else (1 if alien_pct < RED_PCT else 2)
        span = track - 2  # sprite is 2 cells wide
        t = (now // 30) * ALIEN_SPEEDS[mood] % (2 * span)
        pos = t if t <= span else 2 * span - t
        fill = "─" * pos + ALIEN_SPRITES[mood] + "─" * (span - pos)
    return "{} {}{}{}{}{}{}".format(row, RULE, fill, R, NEON_GREEN, corner, R)


def render(data, cols, now):
    """Return [row1, row2] sized to cols."""
    frame_on = os.environ.get("RETRO_HUD_FRAME", "1") != "0"
    cd_pct = num(os.environ.get("RETRO_HUD_COUNTDOWN_PCT"), 75)

    # ── extract fields ──
    cwd = str(dig(data, "workspace", "current_dir") or data.get("cwd") or "~")
    model = str(dig(data, "model", "display_name") or dig(data, "model", "id") or "---")
    effort = str(dig(data, "effort", "level") or "")
    thinking = bool(dig(data, "thinking", "enabled"))
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

    # ── gauge widths scale with the terminal ──
    ctx_len = clamp(cols // 20, 4, 10)
    rl_len = clamp(cols // 40, 3, 6)

    # ── duration ──
    dur_min = dur_ms // 60000
    if dur_min >= 60:
        dur_str = "{}h{:02d}m".format(dur_min // 60, dur_min % 60)
    elif dur_min > 0:
        dur_str = "{}m".format(dur_min)
    else:
        dur_str = "{}s".format(dur_ms % 60000 // 1000)

    # ═══ ROW 1 ═══
    def model_seg(name):
        inner = MODEL_TXT + name + R
        if effort in EFFORT_GLYPHS:
            inner += " " + EFFORT_COLORS[effort] + EFFORT_GLYPHS[effort] + R
        if thinking:
            inner += " " + NEON_CYAN + "✧" + R
        return "{}[{} {} {}]{}".format(MODEL_BOX, R, inner, MODEL_BOX, R)

    def dir_seg(name):
        return NEON_WHT + "\U0001F4C2 " + name + R

    def branch_seg(name):
        return "{} ⎇ {} {}".format(BRANCH_BADGE, link(gh_url, name), R)

    def pr_seg():
        color, glyph = PR_STATE.get(pr_state, PR_STATE["pending"])
        return color + link(pr_url, "#{}{}".format(pr_num, glyph)) + R

    def vim_seg():
        return VIM_COLORS.get(vim_mode, NEON_CYAN) + "[" + vim_mode[0] + "]" + R

    def session_seg(name):
        return DIM + "◈ " + name + R

    t_model, t_dir, t_branch, t_session = model, dir_name, branch, session_name
    show_pr, show_vim, show_session = pr_num > 0, bool(vim_mode), bool(session_name)

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
        if vislen(row1) <= cols:
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
        c = value_color(clamp(ctx_pct, 0, 100))
        s = "{} {}{}%{}".format(ctx_gauge(ctx_pct, ctx_len), c, clamp(ctx_pct, 0, 999), R)
        if tok_mode and ctx_tok:
            t = fmt_tok(ctx_tok)
            if tok_mode == 2 and win_size:
                t += "/" + fmt_win(win_size)
            s += " " + NEON_WHT + t + R
        return s

    rl_mode = os.environ.get("RETRO_HUD_RL_MODE", "cycle")
    if rl_mode not in ("cycle", "pct", "time", "both"):
        rl_mode = "cycle"
    time_phase = rl_mode == "time" or (rl_mode == "cycle" and (now // 30) % 2 == 1)

    def rl_label(pct, left, reset, rich):
        # Escalation ladder: calm → cycle/pinned; ≥ cd_pct → "81% · 3d";
        # red zone → countdown only (the bar already screams the %).
        pct_lbl = "{}%".format(clamp(pct, 0, 999))
        if not reset:
            return pct_lbl
        if pct >= RED_PCT and rl_mode != "both":
            return fmt_countdown(left)
        if rich and (pct >= cd_pct or rl_mode == "both"):
            return pct_lbl + " · " + fmt_countdown(left)
        return fmt_countdown(left) if time_phase else pct_lbl

    def rl_seg(rich):
        return rate_mirror(rl5_pct, rl7_pct, rl_len,
                           rl_label(rl5_pct, rl5_left, rl5_reset, rich),
                           rl_label(rl7_pct, rl7_left, rl7_reset, rich))

    def lines_seg():
        return "{}+{}{}{}/{}{}-{}{}".format(
            NEON_GREEN, lines_add, R, DIM, R, NEON_RED, lines_del, R)

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

    show_lines = lines_add > 0 or lines_del > 0
    show_dur = True
    show_cache = cache_denom > 0 and cols >= 140
    show_agent = bool(agent_name or worktree)
    tok_mode, rl_rich = 2, True

    for step in range(8):
        segs = [ctx_seg(tok_mode)]
        if has_rl:
            segs.append(rl_seg(rl_rich))
        if show_lines:
            segs.append(lines_seg())
        if show_cache:
            segs.append(cache_seg())
        if show_dur:
            segs.append(NEON_PINK + "T:" + dur_str + R)
        segs.append(NEON_YEL + ("${:.2f}".format(cost) if cost < 100 else "${:.0f}".format(cost)) + R)
        if show_agent:
            segs.append(agent_seg())
        row2 = _join(NEON_GREEN + "└─" + R, segs)
        if vislen(row2) <= cols:
            break
        if step == 0:
            show_cache = False
        elif step == 1:
            tok_mode = 1
        elif step == 2:
            rl_rich = False
        elif step == 3:
            show_lines = False
        elif step == 4:
            tok_mode = 0
        elif step == 5:
            show_agent = False
        else:
            show_dur = False

    alien_pct = None
    if os.environ.get("RETRO_HUD_ALIEN", "1") != "0":
        alien_pct = max(clamp(ctx_pct, 0, 100),
                        clamp(rl5_pct, 0, 100) if has_rl else 0,
                        clamp(rl7_pct, 0, 100) if has_rl else 0)

    return [_frame(row1, cols, "┐", frame_on, alien_pct, now),
            _frame(row2, cols, "┘", frame_on)]


# ── entry point ──
DEMO_DATA = {
    "model": {"display_name": "Fable 5"},
    "_branch_override": "main",
    "workspace": {"current_dir": "/home/ripley/projects/nostromo",
                  "repo": {"host": "github.com", "owner": "codyslater",
                           "name": "ccstatusline_retro-hud"}},
    "session_name": "retro-hud-v2",
    "effort": {"level": "max"},
    "thinking": {"enabled": True},
    "vim": {"mode": "INSERT"},
    "agent": {"name": "reviewer"},
    "context_window": {"used_percentage": 42, "total_input_tokens": 84213,
                       "context_window_size": 200000,
                       "current_usage": {"input_tokens": 1900,
                                         "cache_read_input_tokens": 79800,
                                         "cache_creation_input_tokens": 2513,
                                         "output_tokens": 1150}},
    "cost": {"total_cost_usd": 3.21, "total_duration_ms": 5432100,
             "total_lines_added": 128, "total_lines_removed": 37},
    "pr": {"number": 42, "url": "https://github.com/codyslater/ccstatusline_retro-hud/pull/42",
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

    cols = shutil.get_terminal_size((100, 24)).columns
    try:
        rows = render(data, cols, now)
    except Exception:  # never break the statusline — degrade gracefully
        model = dig(data, "model", "display_name") or "retro-hud"
        rows = ["{}┌─{}[ {}{}{} ]{}".format(NEON_GREEN, R, MODEL_TXT, model, R + MODEL_BOX, R),
                "{}└─{} {}(status degraded){}".format(NEON_GREEN, R, DIM, R)]
    print(rows[0])
    print(rows[1], end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
