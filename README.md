# 🎮 retro-hud

A retro sci-fi HUD status line theme for [Claude Code](https://claude.com/claude-code).

![retro-hud](retro-hud.png)

## Features

- Two-row HUD layout with $\color{#00ff00}{\textsf{green}}$ wireframe corners
- $\color{#00ffff}{\textsf{Neon cyan}}$ `//` separators
- Dynamic column sizing based on terminal width
- Fractional-block progress bars with sub-character precision
- Context usage bar with color coding ($\color{#00ff00}{\textsf{green}}$ < 70%, $\color{#ff8700}{\textsf{orange}}$ < 90%, $\color{#ff0000}{\textsf{red}}$)
- I/O token bar showing input/output ratio and total
- Mirrored rate limit display (5-hour and 7-day) with distinct color palettes
- Git branch with clickable GitHub link (OSC 8)
- Effort level indicator dot (when set in settings)
- Agent/worktree indicator when subagents are active
- Session cost and duration tracking
- Double-width emoji support for accurate terminal alignment

### Row 1
| Field | Color | Symbol |
|-------|-------|--------|
| Model + effort | white in $\color{#00ff00}{\textsf{green}}$ `[ ]` box | `·` `•` `●` `⬤` |
| Working directory | white | `📂` |
| Git branch | white on $\color{#af00ff}{\textsf{purple}}$ badge | `⎇` |

### Row 2
| Field | Color | Symbol |
|-------|-------|--------|
| Context % bar | $\color{#00ff00}{\textsf{green}}$ / $\color{#ff8700}{\textsf{orange}}$ / $\color{#ff0000}{\textsf{red}}$ | `█▌` fractional |
| I/O token bar | $\color{#00ffff}{\textsf{cyan}}$ input / $\color{#ffff00}{\textsf{yellow}}$ output | `██` + total |
| Rate limits (mirrored) | $\color{#0087ff}{\textsf{blue}}$ 5h ← \| → $\color{#af5fff}{\textsf{violet}}$ 7d | `██\|██` |
| Duration | $\color{#ff0087}{\textsf{pink}}$ | `⏱` |
| Session cost | $\color{#ffff00}{\textsf{yellow}}$ | `$` |
| Agent status | $\color{#00ffff}{\textsf{cyan}}$ / white | `▐█` or `┄┄┄` idle |

## Requirements

- Python 3.6+
- Claude Code
- A terminal with 256-color support
- Recommended font: JetBrains Mono, Fira Code, or a Nerd Font (for fractional block characters)

## Install

```bash
git clone https://github.com/codyslater/ccstatusline_retro-hud.git
cd ccstatusline_retro-hud
bash install.sh
```

Then restart Claude Code.

## Manual Install

Copy `statusline.py` and `statusline-command.sh` to `~/.claude/`, then add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash ~/.claude/statusline-command.sh"
  }
}
```

### VS Code Terminal Tips

For best results in VS Code's integrated terminal:

```json
{
  "terminal.integrated.unicodeVersion": "11"
}
```

## License

MIT
