#!/usr/bin/env python3
"""Claude Code statusLine — RETRO SCI-FI HUD
Single-line or two-line layout with width-aware truncation.
"""
import json, os, re, shutil, subprocess, sys, time

# Ensure git is findable regardless of Claude Code's PATH
os.environ.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin:" + os.environ.get("PATH", ""))

data = json.load(sys.stdin)

COLS = shutil.get_terminal_size((100, 24)).columns

# ── HIGH CONTRAST sci-fi palette ──
R = "\033[0m"

MODEL_BOX = "\033[1;38;5;46m"
MODEL_TXT = "\033[1;38;5;231m"
BRANCH_BADGE = "\033[1;97;48;5;129m"

NEON_CYAN  = "\033[1;38;5;51m"
NEON_GREEN = "\033[1;38;5;46m"
NEON_YEL   = "\033[1;38;5;226m"
NEON_RED   = "\033[1;38;5;196m"
NEON_PINK  = "\033[1;38;5;198m"
NEON_WHT   = "\033[1;38;5;231m"
NEON_ORG   = "\033[1;38;5;208m"
DIM        = "\033[38;5;240m"

TL = f"{NEON_GREEN}\u250c{R}"
BL = f"{NEON_GREEN}\u2514{R}"
H  = f"{NEON_GREEN}\u2500{R}"
SEP = f" {NEON_CYAN}//{R} "
SEP_PLAIN_LEN = 4  # " // " visible chars

# ── extract fields ──
cwd = data.get("workspace", {}).get("current_dir") or data.get("cwd", "~")
model = data.get("model", {}).get("display_name") or data.get("model", {}).get("id", "---")
ctx_pct = int(data.get("context_window", {}).get("used_percentage") or 0)
cost = float(data.get("cost", {}).get("total_cost_usd") or 0)
dur_ms = int(data.get("cost", {}).get("total_duration_ms") or 0)
in_tok = int(data.get("context_window", {}).get("total_input_tokens") or 0)
out_tok = int(data.get("context_window", {}).get("total_output_tokens") or 0)
agent_name = data.get("agent", {}).get("name", "")
worktree = data.get("worktree", {}).get("name", "")
# Rate limits (5-hour and 7-day windows)
_rl = data.get("rate_limits", {})
rl_5h_pct = int(_rl.get("five_hour", {}).get("used_percentage") or 0)
rl_7d_pct = int(_rl.get("seven_day", {}).get("used_percentage") or 0)

# ── cache for slow lookups (git subprocesses, settings file reads) ──
_CACHE_FILE = os.path.join(os.path.expanduser("~"), ".claude", ".statusline_cache.json")
_CACHE_TTL = 30  # seconds

def _load_cache():
    try:
        with open(_CACHE_FILE) as f:
            c = json.load(f)
        if time.time() - c.get("ts", 0) < _CACHE_TTL and c.get("cwd") == cwd:
            return c
    except Exception:
        pass
    return None

def _save_cache(d):
    d["ts"] = time.time()
    d["cwd"] = cwd
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump(d, f)
    except Exception:
        pass

_cache = _load_cache()
if _cache:
    git_branch = _cache.get("git_branch", "")
    github_url = _cache.get("github_url", "")
else:
    # ── git branch + remote URL (single subprocess) ──
    git_branch = ""
    github_url = ""
    _git_env = {
        **os.environ,
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": "*",
    }
    try:
        _git_out = subprocess.check_output(
            ["sh", "-c",
             'cd "$1" && '
             '{ git symbolic-ref --short HEAD 2>/dev/null || git rev-parse --short HEAD 2>/dev/null; } && '
             'git remote get-url origin 2>/dev/null || true',
             "--", cwd],
            stderr=subprocess.DEVNULL, universal_newlines=True, env=_git_env
        ).strip()
        _lines = _git_out.splitlines()
        if _lines:
            git_branch = _lines[0].strip()
        if len(_lines) >= 2:
            remote = _lines[1].strip()
            m = re.match(r"git@github\.com:(.+?)(?:\.git)?$", remote)
            if not m:
                m = re.match(r"https?://github\.com/(.+?)(?:\.git)?$", remote)
            if m:
                github_url = f"https://github.com/{m.group(1)}/tree/{git_branch}"
    except Exception:
        pass

    _save_cache({"git_branch": git_branch, "github_url": github_url})


# ── duration formatting ──
dur_min = dur_ms // 60000
dur_sec = (dur_ms % 60000) // 1000
if dur_min >= 60:
    dur_str = f"{dur_min // 60}h{dur_min % 60:02d}m"
elif dur_min > 0:
    dur_str = f"{dur_min}m"
else:
    dur_str = f"{dur_sec}s"

# ── dir name (last segment) ──
dir_name = os.path.basename(cwd) or cwd

# ── helpers ──
import unicodedata

def vwidth(s):
    """Visible width accounting for double-width chars (emoji, CJK)."""
    w = 0
    for ch in s:
        cat = unicodedata.east_asian_width(ch)
        w += 2 if cat in ("W", "F") else 1
    return w

_FULL = "\u2588"
_EMPTY = "\u2591"
_FRAC = ["", "\u258F", "\u258E", "\u258D", "\u258C", "\u258B", "\u258A", "\u2589"]

def bar_fill(pct, bar_len, fill_color, empty_color):
    units = pct * bar_len * 8 // 100
    full = units // 8
    frac = units % 8
    empty = bar_len - full - (1 if frac else 0)
    parts = f"{fill_color}{_FULL * full}"
    if frac:
        # Convert empty_color from fg (38;5;X) to bg (48;5;X) for seamless fill
        bg = empty_color.replace("38;5;", "48;5;")
        parts += f"{bg}{_FRAC[frac]}"
    bg = empty_color.replace("38;5;", "48;5;")
    parts += f"{R}{bg}{' ' * empty}{R}"
    return parts

def trunc(s, maxw):
    if maxw <= 2:
        return s[:maxw]
    return s[:maxw-2] + ".." if len(s) > maxw else s

def model_box(name):
    return f"{MODEL_BOX}[{R} {MODEL_TXT}{name} {R}{MODEL_BOX}]{R}"

def ctx_bar(pct, bar_len):
    if pct < 70:
        color = NEON_GREEN
    elif pct < 90:
        color = NEON_ORG
    else:
        color = NEON_RED
    return f"{bar_fill(pct, bar_len, color, chr(27) + '[38;5;22m')} {color}{pct}%{R}"

def fmt_tok(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)

def tok_bar(inp, out, bar_len):
    total = inp + out
    if total == 0:
        return f"{DIM}{_EMPTY * bar_len}{R}"
    in_fill = max(round(inp / total * bar_len), 1 if inp else 0)
    out_fill = bar_len - in_fill
    return f"{NEON_CYAN}{_FULL * in_fill}{R}{NEON_YEL}{_FULL * out_fill}{R} {NEON_WHT}{fmt_tok(total)}{R}"

def rate_bar(pct, bar_len, fill_color, empty_color):
    if pct >= 90:
        fill_color = NEON_RED
    elif pct >= 70:
        fill_color = NEON_ORG
    return f"{bar_fill(pct, bar_len, fill_color, empty_color)} {fill_color}{pct}%{R}"

_FRAC_R = ["", "\u2595", "\u2590"]  # right 1/8, right 1/2 (limited Unicode)

def rate_mirror(pct_5h, pct_7d, bar_len, fc_5h, ec_5h, fc_7d, ec_7d):
    if pct_5h >= 90: fc_5h = NEON_RED
    elif pct_5h >= 70: fc_5h = NEON_ORG
    if pct_7d >= 90: fc_7d = NEON_RED
    elif pct_7d >= 70: fc_7d = NEON_ORG
    bg_5h = ec_5h.replace("38;5;", "48;5;")
    bg_7d = ec_7d.replace("38;5;", "48;5;")
    # 5h: fills right-to-left using left-side fractional blocks (visually reversed)
    units_5h = pct_5h * bar_len * 8 // 100
    full_5h = units_5h // 8
    frac_5h = units_5h % 8
    empty_5h = bar_len - full_5h - (1 if frac_5h else 0)
    left = f"{fc_5h}{pct_5h}%{R} {bg_5h}{' ' * empty_5h}{R}"
    if frac_5h:
        left += f"{bg_5h}{fc_5h}{_FRAC[frac_5h]}{R}"
    left += f"{fc_5h}{_FULL * full_5h}{R}"
    # 7d: fills left-to-right (standard direction)
    units_7d = pct_7d * bar_len * 8 // 100
    full_7d = units_7d // 8
    frac_7d = units_7d % 8
    empty_7d = bar_len - full_7d - (1 if frac_7d else 0)
    right = f"{fc_7d}{_FULL * full_7d}{R}"
    if frac_7d:
        right += f"{bg_7d}{fc_7d}{_FRAC[frac_7d]}{R}"
    right += f"{bg_7d}{' ' * empty_7d}{R} {fc_7d}{pct_7d}%{R}"
    return f"{left}{DIM}|{R}{right}"

def link(url, text):
    if url:
        return f"\033]8;;{url}\a{text}\033]8;;\a"
    return text

def agent_display():
    parts = []
    if agent_name:
        parts.append(f"{NEON_CYAN}\u2590\u2588{R} {NEON_WHT}{agent_name}{R}")
    if worktree:
        parts.append(f"{NEON_PINK}\u2387 {worktree}{R}")
    if not parts:
        return f"{DIM}\u2504\u2504\u2504{R}"
    return " ".join(parts)

# ── dynamic sizing ──
r1_model_len = vwidth(model) + 4
r1_dir_len = vwidth("\U0001F4C2") + 1 + vwidth(dir_name)  # 📂 + space + dir
r1_branch_len = vwidth(f"\u2387 {git_branch} ") if git_branch else 0

r1_fixed = 2  # "┌─"
r1_seps = sum(1 for x in [True, True, git_branch] if x) - 1
r1_natural = r1_fixed + r1_model_len + r1_dir_len + r1_branch_len + r1_seps * SEP_PLAIN_LEN

if r1_natural <= COLS:
    t_dir = dir_name
    t_branch = git_branch
else:
    budget = int(COLS * 0.75) - r1_fixed - r1_model_len - r1_seps * SEP_PLAIN_LEN - 6
    if budget > 0:
        w_dir = max(budget * 40 // 100, 5)
        w_br  = max(budget * 60 // 100, 5) if git_branch else 0
        t_dir = trunc(dir_name, w_dir)
        t_branch = trunc(git_branch, w_br) if git_branch else ""
    else:
        t_dir = trunc(dir_name, 6)
        t_branch = trunc(git_branch, 6) if git_branch else ""

# ── bar sizes ──
ctx_bar_len = max(COLS // 24, 2)
bar_len = max(COLS // 32, 2)
tok_bar_len = bar_len

# ── build row 1 ──
branch_part = ""
if t_branch:
    branch_part = f"{SEP}{BRANCH_BADGE} \u2387 {link(github_url, t_branch)} {R}"

row1 = (
    f"{TL}{H}{model_box(model)}"
    f"{SEP}{NEON_WHT}\U0001F4C2 {t_dir}{R}"
    f"{branch_part}"
)

# ── build row 2 with progressive width-aware truncation ──
cost_fmt = f"${cost:.2f}"

# Visible lengths of each segment
# ctx_bar: bar + space + pct%  |  tok_bar: bar + space + total  |  rate_mirror: pct% + space + bar + | + bar + space + pct%
_seg_ctx = ctx_bar_len + 1 + len(str(ctx_pct)) + 1
_seg_tok = tok_bar_len + 1 + len(fmt_tok(in_tok + out_tok))
_seg_rl = len(str(rl_5h_pct)) + 2 + tok_bar_len + 1 + tok_bar_len + 1 + len(str(rl_7d_pct)) + 1  # pct% bar|bar pct%
_seg_agent = vwidth(agent_name or "\u2504\u2504\u2504") + (4 if agent_name else 0) + SEP_PLAIN_LEN
_seg_dur = 2 + vwidth(dur_str) + SEP_PLAIN_LEN  # T: + dur
_seg_cost = vwidth(cost_fmt) + SEP_PLAIN_LEN

# Core row 2 = "└─" + ctx // tok // rate_mirror // cost (always shown)
r2_core = 2 + _seg_ctx + SEP_PLAIN_LEN + _seg_tok + SEP_PLAIN_LEN + _seg_rl + SEP_PLAIN_LEN + _seg_cost
r2_budget = COLS - r2_core

# Progressively add optional segments in priority order: duration > agent
show_dur = r2_budget >= _seg_dur
if show_dur:
    r2_budget -= _seg_dur
show_agent = r2_budget >= _seg_agent

_RL_5H_FC = "\033[1;38;5;33m"
_RL_5H_EC = "\033[38;5;17m"
_RL_7D_FC = "\033[1;38;5;135m"
_RL_7D_EC = "\033[38;5;54m"

row2 = (
    f"{BL}{H}"
    f"{ctx_bar(ctx_pct, ctx_bar_len)}"
    f"{SEP}{tok_bar(in_tok, out_tok, tok_bar_len)}"
    f"{SEP}{rate_mirror(rl_5h_pct, rl_7d_pct, tok_bar_len, _RL_5H_FC, _RL_5H_EC, _RL_7D_FC, _RL_7D_EC)}"
)
if show_dur:
    row2 += f"{SEP}{NEON_PINK}T:{dur_str}{R}"
row2 += f"{SEP}{NEON_YEL}{cost_fmt}{R}"
if show_agent:
    row2 += f"{SEP}{agent_display()}"

print(row1)
print(row2, end="")
