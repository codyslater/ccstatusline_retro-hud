# 🎮 retro-hud

> A retro sci-fi HUD status line for [Claude Code](https://claude.com/claude-code) — neon wireframe, zoned gauges, and a resident alien.

![release](https://img.shields.io/github/v/tag/codyslater/ccstatusline_retro-hud?label=release&color=39ff14)
![python](https://img.shields.io/badge/python-3.6%2B-blue)
![deps](https://img.shields.io/badge/dependencies-none-purple)
![license](https://img.shields.io/badge/license-MIT-green)

![retro-hud running live in Claude Code](retro-hud-live.png)

Two rows, one closed wireframe, and every number Claude Code will give you —
rendered with width-aware degradation so it never overflows, and a top-level
guard so a malformed payload degrades gracefully instead of crashing.

## Quick start

```bash
git clone https://github.com/codyslater/ccstatusline_retro-hud.git
cd ccstatusline_retro-hud
bash install.sh     # backs up settings.json before touching it
```

Restart Claude Code. Preview any time without it:

```bash
python3 statusline.py --demo
```

To remove: `bash uninstall.sh`.

**Requirements:** Python 3.6+ (stdlib only, no subprocesses), Claude Code
2.1.153+, a 256-color terminal. A font with fractional block characters
(JetBrains Mono, Fira Code, any Nerd Font) makes the gauges crisp.

## What it shows

### Row 1 — identity

| Segment | Looks like | Appears |
|---------|-----------|---------|
| Model + effort + thinking | `[ Fable 5 ◉ ✧ ]` — dot scales `·` `•` `●` `◉` `✦` with effort level, `✧` = extended thinking | always |
| Directory | `📂 my-project` | always |
| Git branch | `⎇ main` on a purple badge, hyperlinked to the repo | in a git repo (read straight from `.git` — works in worktrees and on detached HEADs) |
| Pull request | `#42✓` — green ✓ approved, yellow ○ pending, red ✗ changes requested, dim ◌ draft; hyperlinked | while a PR is open for the branch |
| Vim mode | `[N]` `[I]` `[V]` | vim mode enabled |
| Session name | `◈ fix-login-flow` (capped at 28 cols) | named sessions, wide terminals |

### Row 2 — instruments

| Segment | Looks like | Appears |
|---------|-----------|---------|
| Context gauge | zoned green/amber/red track with fractional fill, `72%` | always |
| Context tokens | `144.2K/200K` (or `/1M`) | from the amber zone up, when headroom is an actionable number (`RETRO_HUD_CTX_TOKENS=always\|never` to pin) |
| Rate limits | mirrored gauges, blue 5h ←`██\|██`→ violet 7d | Claude subscription plans (hidden when the API reports none) |
| Lines changed | `+1447/-455` | when nonzero |
| Cache hit rate | `cache 94%` | terminals ≥ 140 cols |
| Duration / cost | `T:1h29m` / `$40.86` | always |
| Agent / worktree | `▐█ reviewer` / `⎇ feature-x` | `--agent` / `--worktree` sessions |

### Rate-limit label escalation

| Usage | Label behavior |
|-------|----------------|
| < 75% | cycles `35%` ↔ `2h45m` every 30s — the gauge stretches to absorb the width difference, so nothing shifts on a flip |
| 75–89% | pins to the combined `81% · 3d` |
| ≥ 90% | countdown only, in red — the bar already screams the % |

### The resident alien

A text-art alien patrols the top frame rule, blinking as it ping-pongs.
It reacts to your **worst** gauge (context or either rate limit):

| Mood | Sprite | Trigger | Speed |
|------|--------|---------|-------|
| calm | `/o.o\` green | all gauges < 70% | 1× |
| agitated | `>o.o<` amber | any gauge ≥ 70% | 2× |
| red alert | `\o.o/` red | any gauge ≥ 90% | 4× |

Peripheral vision tells you something's hot before you read a number.
Ground it with `RETRO_HUD_ALIEN=0`.

## Configuration

Set these in the `env` block of `~/.claude/settings.json`:

| Env var | Default | Effect |
|---------|---------|--------|
| `RETRO_HUD_FRAME` | `1` | `0` disables the right-edge frame fill |
| `RETRO_HUD_ALIEN` | `1` | `0` grounds the alien |
| `RETRO_HUD_RL_MODE` | `cycle` | rate-limit labels: `cycle`, `pct`, `time`, or `both` |
| `RETRO_HUD_COUNTDOWN_PCT` | `75` | usage % where the combined `81% · 3d` label kicks in |
| `RETRO_HUD_CTX_TOKENS` | `auto` | context token readout: `auto` (amber zone up), `always`, `never` |
| `RETRO_HUD_MARGIN` | `3` | columns kept free at the right edge |
| `RETRO_HUD_WIDTH` | — | hard width override when `$COLUMNS` is wrong |
| `RETRO_HUD_EMOJI` | `2` | `1`: count emoji as one cell; `0`: skip the folder emoji |

The installer sets `"refreshInterval": 5` so countdowns tick, the alien
patrols, and the frame re-fits within seconds of a terminal resize
(Claude Code doesn't re-run the statusline on resize). Manual setup:

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash ~/.claude/statusline-command.sh",
    "refreshInterval": 5
  }
}
```

## Troubleshooting width issues (WSL2, VS Code)

Claude Code's renderer truncates over-wide rows with a `…` at an
undocumented threshold, and some terminals disagree with Unicode about
glyph widths. Symptoms and fixes:

- **Rows end in `…`** → raise the margin: `RETRO_HUD_MARGIN=5`.
- **The two corners don't line up** → your terminal advances emoji one
  cell instead of two: `RETRO_HUD_EMOJI=1` (or `0` to drop the 📂).
  In VS Code, also set `"terminal.integrated.unicodeVersion": "11"`.
- **Width plainly wrong** (half the terminal, wrapping) → `$COLUMNS` is
  lying: pin it with `RETRO_HUD_WIDTH=<cols>`.
- **Want the frame flush to the edge** → `RETRO_HUD_MARGIN=0`.

## Development

```bash
python3 tests.py              # width sweeps, hostile payloads, CLI flags
python3 statusline.py --demo  # render with sample data
```

No dependencies, no subprocesses, no network — git state is read from
`.git/HEAD` and `.git/config` directly. Releases follow
[SemVer](https://semver.org) with `v`-prefixed tags; see
[CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)
