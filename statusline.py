#!/usr/bin/env python3
"""Claude Code statusLine — RETRO SCI-FI HUD
Row 1: ┌─[ MODEL ] >> session // [] dir // ⎇ branch
Row 2: └─ ████░░░░ XX% // $COST // T: dur // agents
Dynamic sizing: natural widths if fits, else truncate to 3/4 screen.
"""
import json, os, re, shutil, subprocess, sys

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
effort = data.get("output_style", {}).get("name", "")
session_name = data.get("session_name", "")

agent_name = data.get("agent", {}).get("name", "")
worktree = data.get("worktree", {}).get("name", "")

# ── git branch + remote URL ──
git_branch = ""
github_url = ""
try:
    git_branch = subprocess.check_output(
        ["git", "-C", cwd, "symbolic-ref", "--short", "HEAD"],
        stderr=subprocess.DEVNULL, text=True
    ).strip()
except Exception:
    try:
        git_branch = subprocess.check_output(
            ["git", "-C", cwd, "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        pass

if git_branch:
    try:
        remote = subprocess.check_output(
            ["git", "-C", cwd, "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        m = re.match(r"git@github\.com:(.+?)(?:\.git)?$", remote)
        if not m:
            m = re.match(r"https?://github\.com/(.+?)(?:\.git)?$", remote)
        if m:
            github_url = f"https://github.com/{m.group(1)}/tree/{git_branch}"
    except Exception:
        pass

# ── duration formatting ──
dur_min = dur_ms // 60000
dur_sec = (dur_ms % 60000) // 1000
if dur_min > 0:
    dur_str = f"{dur_min}m{dur_sec:02d}s"
else:
    dur_str = f"{dur_sec}s"

# ── dir name (last segment) ──
dir_name = os.path.basename(cwd) or cwd

# ── helpers ──
def trunc(s, maxw):
    if maxw <= 2:
        return s[:maxw]
    return s[:maxw-2] + ".." if len(s) > maxw else s

def model_box(name):
    return f"{MODEL_BOX}[{R}{MODEL_TXT} {name} {R}{MODEL_BOX}]{R}"

def ctx_bar(pct, bar_len):
    filled = pct * bar_len // 100
    empty = bar_len - filled
    if pct < 70:
        color = NEON_GREEN
    elif pct < 90:
        color = NEON_ORG
    else:
        color = NEON_RED
    bar = "\u2588" * filled + "\u2591" * empty
    return f"{color}{bar} {pct}%{R}"

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

# ── compute natural (untruncated) visible lengths ──
# Row 1 fields: "┌─" + "[ model ]" + " >> session" + " // [] dir" + " // ⎇ branch "
r1_model_len = len(model) + 4        # "[ model ]"
r1_session_len = len(f">> {session_name}") if session_name else 0
r1_dir_len = len(f"[] {dir_name}")
r1_branch_len = len(f"\u2387 {git_branch} ") if git_branch else 0

r1_fixed = 2  # "┌─"
r1_seps = sum(1 for x in [True, session_name, True, git_branch] if x) - 1
r1_natural = r1_fixed + r1_model_len + r1_session_len + r1_dir_len + r1_branch_len + r1_seps * SEP_PLAIN_LEN

# Row 2 fields: "└─" + bar + " // $X.XX" + " // T: Xm00s" + " // agents"
r2_cost_len = len(f"${cost:.2f}")
r2_dur_len = len(f"T: {dur_str}")
r2_agent_text = agent_name or "\u2504\u2504\u2504"
r2_agent_len = len(r2_agent_text) + (4 if agent_name else 0)  # icon + space

# ── dynamic sizing ──
# If everything fits naturally in COLS, use natural widths.
# Otherwise, allocate 3/4 of COLS and shrink flexible fields proportionally.

# Row 1: flexible fields are session, dir, branch
if r1_natural <= COLS:
    # Everything fits — use natural sizes
    t_session = session_name
    t_dir = dir_name
    t_branch = git_branch
else:
    budget = int(COLS * 0.75) - r1_fixed - r1_model_len - r1_seps * SEP_PLAIN_LEN - 8  # 8 for prefixes (>> [] ⎇ )
    # Distribute budget: session 20%, dir 35%, branch 45%
    if budget > 0:
        w_ses = max(budget * 20 // 100, 3) if session_name else 0
        w_dir = max(budget * 35 // 100, 5)
        w_br  = max(budget * 45 // 100, 5) if git_branch else 0
        t_session = trunc(session_name, w_ses) if session_name else ""
        t_dir = trunc(dir_name, w_dir)
        t_branch = trunc(git_branch, w_br) if git_branch else ""
    else:
        t_session = trunc(session_name, 4) if session_name else ""
        t_dir = trunc(dir_name, 6)
        t_branch = trunc(git_branch, 6) if git_branch else ""

bar_len = max(COLS // 8, 5)

# ── render row 1 ──
branch_part = ""
if t_branch:
    branch_part = f"{SEP}{BRANCH_BADGE} \u2387 {link(github_url, t_branch)} {R}"

session_part = ""
if t_session:
    session_part = f" {NEON_RED}>> {t_session}{R}"

print(
    f"{TL}{H}{model_box(model)}"
    f"{session_part}"
    f"{SEP}{NEON_WHT}[] {t_dir}{R}"
    f"{branch_part}"
)

# ── render row 2 ──
cost_fmt = f"${cost:.2f}"

print(
    f"{BL}{H}{ctx_bar(ctx_pct, bar_len)}"
    f"{SEP}{NEON_YEL}{cost_fmt}{R}"
    f"{SEP}{NEON_PINK}T: {dur_str}{R}"
    f"{SEP}{agent_display()}",
    end=""
)
