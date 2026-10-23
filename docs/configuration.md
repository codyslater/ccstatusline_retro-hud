# Configuration & troubleshooting

## Environment variables

Set these in the `env` block of `~/.claude/settings.json`:

| Env var | Default | Effect |
|---------|---------|--------|
| `RETRO_HUD_FRAME` | `1` | `0` disables the right-edge frame fill |
| `RETRO_HUD_ALIEN` | `1` | `0` grounds the alien |
| `RETRO_HUD_RL_MODE` | `cycle` | rate-limit labels *below* the pin threshold: `cycle` (alternate % ↔ time-to-reset every 30s, every 10s in the red zone), `pct`, `time`, or `both` |
| `RETRO_HUD_COUNTDOWN_PCT` | `70` | usage % where the label stops rotating and pins the combined `81% · 3d`; defaults to the amber zone |
| `RETRO_HUD_CTX_TOKENS` | `auto` | context token readout: `auto` (amber zone up), `always`, `never` |
| `RETRO_HUD_MARGIN` | `4` | columns kept free at the right edge (Claude Code's prompt footer insets the status line by 4) |
| `RETRO_HUD_WIDTH` | — | hard width override when `$COLUMNS` is wrong |
| `RETRO_HUD_EMOJI` | `2` | `1`: count emoji as one cell; `0`: skip the folder emoji |
| `RETRO_HUD_HOME_URL` | — | end row 2 with a hyperlinked `⌂`: a jump-home link for multi-session setups. Point it at any URL your desktop can open, e.g. a custom scheme that switches tmux sessions. Unset or empty: no glyph |

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

## Troubleshooting width issues (resize, WSL2, VS Code)

Claude Code draws the status line inside its prompt footer, which pads
2 columns on each side, and cuts any row wider than that box with a `…`
(it measures the row the same way the HUD does, so glyph widths are not
the problem on a standard terminal). The default `RETRO_HUD_MARGIN=4`
keeps both rows inside it. Symptoms and fixes:

- **Right edge turns into `…` (or stops short) right after a resize** →
  expected for a few seconds. Claude Code does not re-run the status line
  when the terminal is resized; it keeps showing the last output until the
  next `refreshInterval` tick (or the next message). Narrowing makes that
  stale row too wide, so it is cut with `…`; widening leaves the frame
  short of the edge. It corrects itself on the next refresh. To shorten
  the window, lower `refreshInterval` (e.g. `2`); to ride out small
  narrowings with no `…` at all, raise the margin (each extra column
  absorbs one column of narrowing).
- **Rows always end in `…`** → something insets the footer further:
  if you set `statusLine.padding`, add twice that value to the margin
  (e.g. `"padding": 1` → `RETRO_HUD_MARGIN=6`); otherwise try
  `RETRO_HUD_MARGIN=5`.
- **The two corners don't line up** → your terminal advances emoji one
  cell instead of two: `RETRO_HUD_EMOJI=1` (or `0` to drop the 📂).
  In VS Code, also set `"terminal.integrated.unicodeVersion": "11"`.
- **Width plainly wrong** (half the terminal, wrapping) → `$COLUMNS` is
  lying: pin it with `RETRO_HUD_WIDTH=<cols>`.
- **Gap at the right edge** → in a presentation mode where the footer
  has no side padding (some fullscreen setups), the status line can use
  the full width: lower the margin, down to `RETRO_HUD_MARGIN=0`.
