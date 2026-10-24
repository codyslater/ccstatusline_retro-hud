# Configuration & troubleshooting

## Environment variables

Set these in the `env` block of `~/.claude/settings.json`:

| Env var | Default | Effect |
|---------|---------|--------|
| `RETRO_HUD_FRAME` | `1` | `0` disables the right-edge frame fill |
| `RETRO_HUD_CREATURE` | `tiny` | the [pixel creature](../README.md#agent-presence)'s size. `tiny`: braille dots in a 7-cell box on the top rule, two lines. `big`: half blocks straddling rows 1 and 2, two lines. `tall`: half blocks with a head line above the frame, three lines. `0` restores the 2.x two-row HUD with the text-art alien, byte for byte. Any other value is `tiny`. A `size` in the session's state file (the click menu's *size ▸*) wins over it, except that `0` is always off |
| `RETRO_HUD_TICK_S` | `1` | seconds per animation frame: the creature's frame index is the time divided by this (a positive integer; anything else is `1`). It moves once per frame when Claude Code redraws often enough: set `statusLine.refreshInterval` to `1` for motion every second |
| `RETRO_HUD_EXCURSIONS` | `1` | `0` keeps the creature on its rule: no [excursions](../README.md#agent-presence) over the rest of the bar (`tiny` and `big` only; `tall` never goes) |
| `RETRO_HUD_CREATURE_SEED` | session id | pins the creature's body and colour: any integer or string (strings are hashed with CRC-32). A `seed` in the session's state file (the click menu's *reroll*) wins over it |
| `RETRO_HUD_CREATURE_COLOR` | from the seed | pins the body colour: `pink`, `green`, `purple`, `cyan`, `orange`, a 256-colour index `0`–`255`, or `mood` (the seed's colour, recoloured only by attention states: yellow needs you, pink error, dim idle and asleep; the `tiny` alien is green unless pinned). Amber and red still take over when a gauge is hot |
| `RETRO_HUD_ALIEN` | `1` | `0` grounds the creature (or the 2.x alien) and with it all agent presence: no transcript reads, no files. With `tall` the head line stays, blank |
| `RETRO_HUD_PRESENCE` | `1` | `0` restores the gauge-only creature: it reacts to the gauges but not to what the agent is doing |
| `RETRO_HUD_SPRITE` | `alien` | creature family: `blob`, `beast`, `alien`, `bot`, `robot` (the 2.x names `cat` and `ghost` map to `beast` and `blob`; `robot` is its own family since 3.1). With `RETRO_HUD_CREATURE=0`, the text-art set: `alien`, `cat`, `robot`, `ghost` |
| `RETRO_HUD_SESSION_NAME` | `1` | the `◈ name` segment (Claude Code's session name, the agent menu's link): `0` drops it (the creature's cloud reaches the same menu with `m`) |
| `RETRO_HUD_AGENT_NAME` | — | name the agent that lives in this terminal; prefixes state bubbles (`Nova: ready`) |
| `RETRO_HUD_BUBBLES` | `alerts` | what the creature may say: `alerts` = only `need you` / `compact?` / `limit soon` plus events-channel messages; `all` = also `ready`, `hm.`, `z`/`zZ` and idle quips; `off` = nothing |
| `RETRO_HUD_QUIPS` | `1` | `0` turns off the rare idle quips |
| `RETRO_HUD_IDLE_MIN` | `10` | minutes of "your turn" before the creature goes idle |
| `RETRO_HUD_SLEEP_MIN` | `60` | minutes of "your turn" before it falls asleep |
| `RETRO_HUD_CACHE_DIR` | `~/.cache/retro-hud` | where the per-session state, events and hook files live (falls back to `/tmp/retro-hud-<uid>` without a usable home). `presence-hook.sh` honours it too |
| `RETRO_HUD_COST_MODE` | `cycle` | `cycle`: duration and cost share one field, alternating every 30s and padded to the wider label so the flip moves nothing; `both`: two segments (`T:…` and `$…`) |
| `RETRO_HUD_RL_MODE` | `cycle` | rate-limit labels *below* the pin threshold: `cycle` (alternate % ↔ time-to-reset every 30s, every 10s in the red zone), `pct`, `time`, or `both` |
| `RETRO_HUD_COUNTDOWN_PCT` | `70` | usage % where the label stops rotating and pins the combined `81% · 3d`; defaults to the amber zone |
| `RETRO_HUD_CTX_TOKENS` | `auto` | context token readout: `auto` (amber zone up), `always`, `never` |
| `RETRO_HUD_MARGIN` | `4` | columns kept free at the right edge (Claude Code's prompt footer insets the status line by 4) |
| `RETRO_HUD_WIDTH` | — | hard width override when `$COLUMNS` is wrong |
| `RETRO_HUD_EMOJI` | `2` | `1`: count emoji as one cell; `0`: skip the folder emoji |
| `RETRO_HUD_AT_HOME` | — | `1` when this session is the home session: the `⌂` is not shown there; after a `⌂` click a `↩` shows instead (see `RETRO_HUD_BACK_URL`) |
| `RETRO_HUD_BACK_URL` | — | the return button's URL (`↩`, outside the frame past the `┘`): shown on the home session while `<cache>/home-from` names the session a `⌂` click came from; the handler writes that file on a home click and removes it on a return |
| `RETRO_HUD_HOME_URL` | — | a hyperlinked `⌂` outside the frame at the far right (past the `┐`; the blank cell under it carries the same link, so either row clicks); the column stays reserved on the home session so the end bars line up: a jump-home link for multi-session setups. Point it at any URL your desktop can open, e.g. a custom scheme that switches tmux sessions. Unset or empty: no glyph |
| `RETRO_HUD_ACTIONS` | — | `1` turns on [click actions](../README.md#click-actions): model, effort, context gauge, cost and lines link to `retro-hud://…` inside tmux; the rate-limit gauges link to `retro-hud://usage` everywhere. A comma list (`model,diff,agent,card`) links only those actions (names: `model`, `effort`, `ctx`, `cost`, `diff`, `usage`, `agent`, `card`); the rest render plain. Needs a scheme handler (`install.sh --handler`); for click menus at the pointer, the tmux binding in the README ("Click in tmux"). Any other value: off, output unchanged |

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
countdowns tick, the creature moves, and the frame re-fits within seconds of
a terminal resize (Claude Code doesn't re-run the statusline on resize, so
the interval is what picks up the new width). Agent presence **requires**
it: without it the idle and asleep states never show and bubbles don't
expire until the next message.
Set it to `1` to watch the creature move every second (one frame per
`RETRO_HUD_TICK_S`, default 1 s); at 5 you see the same motion sampled
every 5 seconds.

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
