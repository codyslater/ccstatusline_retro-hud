# Configuration & troubleshooting

## Environment variables

Set these in the `env` block of `~/.claude/settings.json`:

| Env var | Default | Effect |
|---------|---------|--------|
| `RETRO_HUD_FRAME` | `1` | `0` disables the right-edge frame fill |
| `RETRO_HUD_ALIEN` | `1` | `0` grounds the alien (and with it all agent presence: no transcript reads, no files) |
| `RETRO_HUD_PRESENCE` | `1` | `0` restores the gauge-only alien: it reacts to the gauges but not to what the agent is doing |
| `RETRO_HUD_SPRITE` | `alien` | presence sprite set: `alien`, `cat`, `robot`, `ghost` |
| `RETRO_HUD_AGENT_NAME` | — | name the agent that lives in this terminal; prefixes state bubbles (`Nova: ready`) |
| `RETRO_HUD_QUIPS` | `1` | `0` turns off the rare idle quips |
| `RETRO_HUD_IDLE_MIN` | `10` | minutes of "your turn" before the alien goes idle |
| `RETRO_HUD_SLEEP_MIN` | `60` | minutes of "your turn" before it falls asleep |
| `RETRO_HUD_CACHE_DIR` | `~/.cache/retro-hud` | where the per-session state, events and hook files live (falls back to `/tmp/retro-hud-<uid>` without a usable home). `presence-hook.sh` honours it too |
| `RETRO_HUD_RL_MODE` | `cycle` | rate-limit labels *below* the pin threshold: `cycle` (alternate % ↔ time-to-reset every 30s, every 10s in the red zone), `pct`, `time`, or `both` |
| `RETRO_HUD_COUNTDOWN_PCT` | `70` | usage % where the label stops rotating and pins the combined `81% · 3d`; defaults to the amber zone |
| `RETRO_HUD_CTX_TOKENS` | `auto` | context token readout: `auto` (amber zone up), `always`, `never` |
| `RETRO_HUD_MARGIN` | `4` | columns kept free at the right edge (Claude Code's prompt footer insets the status line by 4) |
| `RETRO_HUD_WIDTH` | — | hard width override when `$COLUMNS` is wrong |
| `RETRO_HUD_EMOJI` | `2` | `1`: count emoji as one cell; `0`: skip the folder emoji |
| `RETRO_HUD_HOME_URL` | — | end row 2 with a hyperlinked `⌂`: a jump-home link for multi-session setups. Point it at any URL your desktop can open, e.g. a custom scheme that switches tmux sessions. Unset or empty: no glyph |
| `RETRO_HUD_ACTIONS` | — | `1` turns on [click actions](../README.md#click-actions): model, effort, context gauge, cost and lines link to `retro-hud://…` inside tmux; the rate-limit gauges link to `retro-hud://usage` everywhere. Needs a scheme handler (`install.sh --handler`). Any other value: off, output unchanged |

Example:

```json
{
  "env": {
    "RETRO_HUD_CTX_TOKENS": "always",
    "RETRO_HUD_MARGIN": "5"
  }
}
```

### Click-action handler settings

The reference handler (`~/.claude/retro-hud-handler.sh`) is started by
your desktop when you click a link, so it never sees your shell's
exports or this `env` block. It reads these from its own environment
first, then from `~/.config/retro-hud/env` — plain `KEY=VALUE` lines,
parsed line by line, never sourced; unknown keys are ignored and logged:

| Key | Default | Effect |
|-----|---------|--------|
| `RETRO_HUD_MODELS` | `opus,sonnet,haiku` | comma list for the model menu; each entry may use letters, digits and `. _ : - [ ]` (e.g. `opus[1m]`) |
| `RETRO_HUD_USAGE_URL` | `https://claude.ai/settings/usage` | page the rate-limit gauges open; must be `http(s)://` |
| `RETRO_HUD_AGENT_NAME` | `agent` | title of the agent menu; letters, digits, space and `. _ -`, up to 24 |
| `RETRO_HUD_CACHE_DIR` | `~/.cache/retro-hud` | where the agent menu finds the HUD's presence files; set it here only if you set it for the statusline too |

```
# ~/.config/retro-hud/env
RETRO_HUD_MODELS=opus,sonnet,opus[1m]
```

`install.sh --handler` (or `--handler-only`, which leaves the statusline
alone) creates this file with commented defaults if it doesn't exist.
Rejected clicks and handler problems are logged to
`~/.cache/retro-hud/handler.log`.

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

`refreshInterval` re-renders every 5 seconds while idle so rate-limit
countdowns tick, the alien patrols, and the frame re-fits within seconds of
a terminal resize (Claude Code doesn't re-run the statusline on resize, so
the interval is what picks up the new width). Agent presence **requires**
it: without it the idle and asleep states never show and bubbles don't
expire until the next message.

### Presence hooks (manual)

`bash install.sh --hooks` does this for you. To do it by hand, copy
`presence-hook.sh` to `~/.claude/` and add:

```json
{
  "hooks": {
    "Stop": [{"hooks": [{"type": "command", "command": "bash ~/.claude/presence-hook.sh yours"}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "bash ~/.claude/presence-hook.sh working"}]}],
    "Notification": [
      {"matcher": "permission_prompt", "hooks": [{"type": "command", "command": "bash ~/.claude/presence-hook.sh needs"}]},
      {"matcher": "idle_prompt", "hooks": [{"type": "command", "command": "bash ~/.claude/presence-hook.sh yours idle_prompt"}]}
    ]
  }
}
```

Each run appends `{"ts": <epoch>, "state": "..."}` to
`~/.cache/retro-hud/<session_id>.hooks.jsonl`. The script prints nothing
and always exits 0, so it can never block a turn.

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
