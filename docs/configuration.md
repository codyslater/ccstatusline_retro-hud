# Configuration & troubleshooting

## Environment variables

Set these in the `env` block of `~/.claude/settings.json`:

| Env var | Default | Effect |
|---------|---------|--------|
| `RETRO_HUD_FRAME` | `1` | `0` disables the right-edge frame fill |
| `RETRO_HUD_ALIEN` | `1` | `0` grounds the alien |
| `RETRO_HUD_RL_MODE` | `cycle` | rate-limit labels: `cycle` (alternate % ↔ time-to-reset every 30s), `pct`, `time`, or `both` |
| `RETRO_HUD_COUNTDOWN_PCT` | `75` | usage % where the combined `81% · 3d` label kicks in |
| `RETRO_HUD_CTX_TOKENS` | `auto` | context token readout: `auto` (amber zone up), `always`, `never` |
| `RETRO_HUD_MARGIN` | `3` | columns kept free at the right edge |
| `RETRO_HUD_WIDTH` | — | hard width override when `$COLUMNS` is wrong |
| `RETRO_HUD_EMOJI` | `2` | `1`: count emoji as one cell; `0`: skip the folder emoji |

Example:

```json
{
  "env": {
    "RETRO_HUD_CTX_TOKENS": "always",
    "RETRO_HUD_MARGIN": "5"
  }
}
```

## Manual install

Copy `statusline.py` and `statusline-command.sh` to `~/.claude/`, then add
to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash ~/.claude/statusline-command.sh",
    "refreshInterval": 5
  }
}
```

`refreshInterval` is optional but recommended: it re-renders every 5 seconds
while idle so rate-limit countdowns tick, the alien patrols, and the frame
re-fits within seconds of a terminal resize (Claude Code doesn't re-run the
statusline on resize, so the interval is what picks up the new width).

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
