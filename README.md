# 🎮 retro-hud

A retro sci-fi HUD status line theme for [Claude Code](https://claude.com/claude-code).

![retro-hud](retro-hud.png)

## Features

- Two-row HUD with a full $\color{#00ff00}{\textsf{green}}$ wireframe — corner brackets on both edges, joined by a dim rule
- $\color{#00ffff}{\textsf{Neon cyan}}$ `//` separators
- Zoned context gauge: $\color{#00ff00}{\textsf{green}}$ / $\color{#ff8700}{\textsf{amber}}$ / $\color{#ff0000}{\textsf{red}}$ zones tinted into the empty track like a redlined instrument, fractional-block fill with sub-character precision
- Context tokens next to the gauge (`42% 84.2K/200K`), aware of 200K vs 1M context windows
- Mirrored rate-limit gauges ($\color{#0087ff}{\textsf{blue}}$ 5h ← | → $\color{#af5fff}{\textsf{violet}}$ 7d) with escalating labels: calm windows alternate between usage % and time-to-reset every 30s, above 75% both are shown together (`81% · 3d`), and in the $\color{#ff0000}{\textsf{red zone}}$ (≥90%) the label switches to time-to-reset only — hidden entirely on plans without rate limits
- Git branch badge with clickable repo link (OSC 8), read directly from `.git` — no subprocess, works in worktrees and on detached HEADs
- PR badge (`#42✓`) colored by review state, hyperlinked to the PR
- Effort-level dot in the model box (`·` `•` `●` `⬤` `✦`) and `✧` when extended thinking is on
- Vim mode badge (`[N]` `[I]` `[V]`) when vim mode is enabled
- Lines added/removed, session cost, duration, prompt-cache hit rate (wide terminals), session name, and agent/worktree indicators
- A resident alien 👾 patrols the top frame rule, ping-ponging along it as the HUD refreshes; it gets agitated 👽 and doubles speed when any gauge passes 70%, and calls in the mothership 🛸 at 4× speed in the red zone (`RETRO_HUD_ALIEN=0` to ground it)
- Width-aware progressive degradation: segments truncate, then drop, in priority order — rows never overflow the terminal
- Double-width emoji handling for accurate alignment; crash-proof against missing or malformed payload fields

### Row 1

| Field | Color | Symbol |
|-------|-------|--------|
| Model + effort + thinking | white in $\color{#00ff00}{\textsf{green}}$ `[ ]` box | `·` `•` `●` `⬤` `✦`, `✧` |
| Working directory | white | `📂` |
| Git branch (linked) | white on $\color{#af00ff}{\textsf{purple}}$ badge | `⎇` |
| Pull request (linked) | $\color{#00ff00}{\textsf{green}}$ / $\color{#ffff00}{\textsf{yellow}}$ / $\color{#ff0000}{\textsf{red}}$ by review state | `#42✓` |
| Vim mode | mode-colored | `[N]` `[I]` `[V]` |
| Session name | dim | `◈` |

### Row 2

| Field | Color | Symbol |
|-------|-------|--------|
| Context gauge + tokens | zoned $\color{#00ff00}{\textsf{green}}$ / $\color{#ff8700}{\textsf{amber}}$ / $\color{#ff0000}{\textsf{red}}$ | `█▌` fractional |
| Rate limits (mirrored) | $\color{#0087ff}{\textsf{blue}}$ 5h ← \| → $\color{#af5fff}{\textsf{violet}}$ 7d | `██\|██` + countdown |
| Lines added/removed | $\color{#00ff00}{\textsf{green}}$ / $\color{#ff0000}{\textsf{red}}$ | `+128/-37` |
| Cache hit rate | $\color{#00ffff}{\textsf{cyan}}$ (terminals ≥ 140 cols) | `cache 94%` |
| Duration | $\color{#ff0087}{\textsf{pink}}$ | `T:` |
| Session cost | $\color{#ffff00}{\textsf{yellow}}$ | `$` |
| Agent / worktree | $\color{#00ffff}{\textsf{cyan}}$ / $\color{#ff0087}{\textsf{pink}}$ | `▐█` / `⎇` |

## Requirements

- Python 3.6+
- Claude Code 2.1.153+ (needed for the `COLUMNS` width variable; rate-limit,
  PR, and effort fields light up automatically on versions that provide them)
- A terminal with 256-color support
- Recommended font: JetBrains Mono, Fira Code, or a Nerd Font (for fractional block characters)

## Install

```bash
git clone https://github.com/codyslater/ccstatusline_retro-hud.git
cd ccstatusline_retro-hud
bash install.sh
```

Then restart Claude Code. The installer backs up your existing
`settings.json` before touching it. To remove: `bash uninstall.sh`.

Preview without Claude Code:

```bash
python3 statusline.py --demo
```

## Manual Install

Copy `statusline.py` and `statusline-command.sh` to `~/.claude/`, then add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash ~/.claude/statusline-command.sh",
    "refreshInterval": 30
  }
}
```

`refreshInterval` is optional; it re-renders every 30s while idle so the
rate-limit countdowns keep ticking.

## Configuration

| Env var | Default | Effect |
|---------|---------|--------|
| `RETRO_HUD_FRAME` | `1` | Set `0` to disable the right-edge frame fill |
| `RETRO_HUD_COUNTDOWN_PCT` | `75` | Rate-limit % at which the combined `81% · 3d` label appears |
| `RETRO_HUD_RL_MODE` | `cycle` | Rate-limit labels: `cycle` alternates % ↔ time-to-reset every 30s; `pct`, `time`, or `both` pin one style |
| `RETRO_HUD_ALIEN` | `1` | Set `0` to ground the alien patrolling the top rule |

Set them in the `env` block of `~/.claude/settings.json`.

### VS Code Terminal Tips

For best results in VS Code's integrated terminal:

```json
{
  "terminal.integrated.unicodeVersion": "11"
}
```

## Development

```bash
python3 tests.py        # width safety, hostile payloads, CLI behavior
python3 statusline.py --demo
```

Releases follow [SemVer](https://semver.org) with `v`-prefixed tags
(see [CHANGELOG.md](CHANGELOG.md)).

## License

MIT
