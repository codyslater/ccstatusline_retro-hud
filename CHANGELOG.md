# Changelog

All notable changes to retro-hud are documented here.
Versioning follows [Semantic Versioning](https://semver.org) with `v`-prefixed
tags from v2.0.0 onward (earlier releases were tagged `1.0`–`1.3`).

## [v3.1.2] — 2026-10-24

### Fixed
- **The return button works with a strict handler too**: `retro-hud://back`
  (and `home`) carry the pane and socket like every action; a handler that
  accepted only the bare form rejected the click.
- **No hidden link beside the buttons.** The blank cell under the `⌂` (or
  above the `↩`) is plain; it used to carry the link and show a hover
  tooltip over nothing.
- **The `↩` means the session you were in before you came home**, whatever
  brought you home through the handler (`⌂`, the session list, the
  needs-you key, `switch`); a record older than 12 h is ignored, so a fresh
  start on home shows nothing. The list's items re-enter the handler.

### Changed
- README: one GIF at the top with the default look, and a fuller demo
  staged on an orbit-propagator project.

## [v3.1.1] — 2026-10-24

### Fixed
- **The home and back buttons sit right after the corners**, with no gap
  cell: the frame now ends one column before the bar's edge, not two.
  README media regenerated.

## [v3.1.0] — 2026-10-24

### Added
- **A `robot` creature family.** Built from parts the seed picks — an
  antenna (one, two, a dish, ears or a flat top), square eyes, a visor or
  dots, a neck, arms down, out, up or none, a chest panel or lights, two
  legs, treads or a pole — so every seed is unmistakably a robot. It is
  12×8 dots and draws in braille on two text rows at `big` (across the two
  HUD lines) and `tall` (the head line and row 1), in a 9-cell box that
  walks in half cells; at `tiny` the same parts make a 10×4 robot on the
  one line (antenna, head with eye holes, body, legs). It walks, hops,
  blinks and breathes, waves its arm tips when the turn is yours, bounces
  with a `?` when it needs you, blinks slowly when idle, powers down flat
  when asleep, shakes on error, jitters in the red zone and widens its
  eyes when agitated. `RETRO_HUD_SPRITE=robot`, or **sprite ▸ robot** in
  the agent menu.

- **`RETRO_HUD_CREATURE_COLOR=mood`.** The creature keeps its seeded
  colour (sessions still tell apart) and recolours only when something
  wants you: yellow when it needs you, pink on error, dim when idle or
  asleep. Amber and red still take over when a gauge is hot.

- **`RETRO_HUD_ACTIONS` takes a list.** `model,diff,agent,card` links
  only those actions; context, cost and the rate-limit gauges render
  plain. For terminals that underline every hyperlink.

- **A session switcher for everyone.** `RETRO_HUD_SESSIONS=1` puts `▣ N`
  on the bar (the other Claude sessions the presence cache knows, `⚑ M`
  needing you); a click opens `retro-hud://sessions`, a list at the
  pointer of every tmux session running Claude with its state word and
  age, needs-you first, click to switch. `retro-hud://needs` jumps to the
  first that needs you (bind it to a key), `retro-hud://switch?to=<name>`
  goes to one, `retro-hud://home` to `RETRO_HUD_HOME_SESSION` and
  `retro-hud://back` to where a home click came from. README, "Sessions".
- **`RETRO_HUD_SESSION_NAME=0`** drops the `◈ name` segment; the creature's
  cloud reaches the agent menu with `m`, so no button is needed.
- **The home button stands outside the frame, and a return button
  answers it.** Away from home the `⌂` sits past the `┐` at the far
  right; on the home session (`RETRO_HUD_AT_HOME=1`) after a `⌂` click a
  `↩` (`RETRO_HUD_BACK_URL`) sits past the `┘` and goes back to the
  session you came from, recorded by the handler in `<cache>/home-from`;
  started on home, neither shows. The column is always reserved, so the
  end bars line up. The other cell of the column carries the same link.
  When the frame has no room the `⌂` falls back to a segment.
- **The creature visits the bottom line twice as often** (the downstairs
  excursion), when row 2 has room.
- **The card is a speech cloud inside the click binding**: a small rounded
  popup above the creature with the highlights; `m` opens the menu, `c`
  the full card, a click on the box or any key closes it.
- **The diff on a clean tree shows the last commit** instead of a blank
  pager; `q` closes, the wheel scrolls. A local extension may point the
  diff at another tree with `RETRO_HUD_DIFF_DIR`.

### Changed
- **The `✧` extended-thinking mark is gone** (no longer a Claude Code
  option); the model box shows the model and the effort dot.
- **Clicks close popups.** A click inside the cloud or card closes it;
  the diff pager closes on `q`.
- **The segment ladder keeps two cells for the frame**, so a bar never
  prints without its corner because its segments fit exactly.
- **Duration ↔ cost field rounds hard** so its width stays put as it
  flips: whole hours from 1h (`2h`), minutes to the nearest five below,
  two significant figures of cost (`$3.2`, `$21`, `$210`, `$1.2k`); the
  `T:` prefix is gone, the pink colour marks the duration. The field is no
  longer padded to its wider label: one space before `//` either way.
- `robot` no longer means the `bot` family: a session whose state file or
  `RETRO_HUD_SPRITE` says `robot` gets the new robot. `cat` and `ghost`
  still map to `beast` and `blob`.

## [v3.0.0] — 2026-10-22

### Fixed
- **Typed actions refused panes where Claude runs under a launcher**
  (`pane_current_command` is the wrapper): a direct child named `claude`
  now counts.
- **Menus closed on the right button's release, and ignored mouse clicks.**
  A `display-menu` the handler runs from outside a key binding has no
  mouse event, and tmux 3.4 then makes it a keyboard-only menu that any
  other mouse button closes — the release of the right-click that opened
  it, a few ms later (`-O` never applied). Inside a tmux right-click
  binding the handler now receives `RETRO_HUD_MENU_FILE` and writes its
  menu there as one `display-menu` line; the binding `source-file`s it,
  so the menu runs with the click's mouse event: it opens at the pointer
  (above it, so the release lands outside), takes clicks, and a press
  outside, Esc or q closes it. README, "Right-click in tmux", has the
  binding. `RETRO_HUD_CLIENT` from the binding names the clicking client.
  Through Ctrl+click and the desktop handler nothing changes.
- `install.sh --hooks-only` registers the presence hooks and touches nothing
  else, for an install whose `statusline.py` or `statusline-command.sh`
  carries local edits (a plain install, `--hooks` or `--handler` included,
  copies both files and resets `statusLine.refreshInterval`).

### Changed (breaking)
- **The alien becomes a living pixel creature.** By default
  (`RETRO_HUD_CREATURE=tiny`) it is drawn in braille dots on the top rule
  and the HUD stays two lines; rows 1 and 2 keep their content, width and
  corners. `RETRO_HUD_CREATURE=0` restores the v2.9.0 two-row output byte
  for byte, text-art alien included.
- **The creature moves on its own clock.** The frame index is the time
  divided by `RETRO_HUD_TICK_S` (default 1 s) instead of a fixed 10 s
  tick, and the creature wanders instead of pacing end to end. Set
  `statusLine.refreshInterval` to 1 to see it move every second; at 5 it
  is the same motion sampled every 5 s.

### Added
- **The creature's status card.** Right-click (or Ctrl+click) the creature
  and a popup shows the session: state and how long, model and effort,
  context %, worst limit %, cost and duration, lines, directory, plus one
  tip (a different one every ten minutes). Any key closes it; `m` opens
  the agent menu, and the agent menu's first item opens the card (for a
  terminal too narrow to show the creature). The creature now links to `retro-hud://card`; the
  session-name segment (`◈ name`, row 1) carries the `retro-hud://agent`
  menu link. The state file gains the card's facts (`model`, `effort`,
  `dur_s`, `lines_add`, `lines_del`, `dir`). A
  `~/.claude/retro-hud-handler.local.sh` may render its own card.
- **Sizes** (`RETRO_HUD_CREATURE`):
  - `tiny` (default): braille, 2×4 dots per cell, a 10×4-dot body in a
    fixed 7-cell box on the top rule, moving in half cells (a one-dot
    step re-draws the cells). One colour per cell, so eyes are holes.
    Hidden below an 11-cell rule.
  - `big`: half blocks (`▀` `▄`, a 256-colour foreground and background
    per cell), a 9×4-pixel body in a fixed 13-cell box straddling rows 1
    and 2 on the stretch of rule they share; still two lines. Hidden
    below a 17-cell shared rule.
  - `tall`: the same half-block body with its upper half on a head line
    above the frame: three lines, always (a blank head line when it
    hides).
- **One creature per session**, generated from a seed (the session id, or
  `RETRO_HUD_CREATURE_SEED`): mirrored, 4-connected, two eyes, legs
  underneath. Families (`RETRO_HUD_SPRITE`): `alien` (default), `beast`,
  `blob`, `bot`; the 2.x sprite names map to them (`cat` → beast,
  `robot` → bot, `ghost` → blob). In `tiny` the alien keeps the 2.x guy
  at dot scale: two round eyes (`o.o`), arms splayed up from the top
  corners, green; it blinks to a slit (`-.-`), pulls its arms in and down
  when agitated (`>o.o<`) and throws them up in the red zone (`\o.o/`).
- Colour from the seed: pink, green, purple or cyan;
  `RETRO_HUD_CREATURE_COLOR` pins a name or a 256-colour index. The body
  turns amber (agitated) or red (red zone) under a hot gauge; otherwise
  the mood shows in the pose and the eyes.
- **Alive behaviour**, in every size, deterministic from (seed, frame):
  it wanders (eases toward a seeded spot, rests 2–6 frames, picks
  another; faster while working), blinks (about one frame in seven),
  breathes (one dot or pixel wider every fourth frame) and hops while
  calm or working (about one frame in twelve).
- **Excursions** (`tiny` and `big`): every 5–15 minutes, for 4–20 s, a
  calm, idle or waiting creature explores the bar: it stretches to double
  width, peeks round the right corner, crawls over row 1's words, visits
  row 2 (sometimes sitting on the duration/cost field) or hangs upside
  down from the top-right corner. Never while working, waiting on a
  prompt, after an error, under a hot gauge or with a bubble or icon to
  show; never in `tall`. A cell compositor lays it over the rows' cells,
  keeping every colour and link escape, never covering the corners or
  leads, never changing a row's width. Deterministic from (seed, clock);
  `RETRO_HUD_EXCURSIONS=0` turns it off, byte for byte.
- Poses: a walk cycle while working, stops and waves when the turn is
  yours (a jump as it starts), a bounce with a yellow `?` when a prompt
  waits, slow blinks when idle, flat on the rule when asleep, a shake on
  an error burst (pink `x` eyes in the half-block sizes), jitters in the
  red zone (`big`/`tall` spin once first), wide eyes when agitated. When a
  mood starts the creature scatters into loose dots and reassembles over
  10s. Parked moods walk to the left end of the rule and stay there.
  Every frame is a pure function of seed, mood, mood start and clock: a
  refresh never re-rolls it.
- Bubbles sit beside the creature on the rule (`tiny`, `big`) or on the
  head line (`tall`); the alerts-only default is unchanged.
- Events-channel lines may carry `"icon": "<one character>"`, which the
  creature holds up in yellow beside its head while the line is live
  (with or without `text`).
- The state file records `mood` and `mood_since` (when the current mood
  began; it times the entry tics) and `creature` (the family, so the
  click menu knows the creature is on). A `seed`, `sprite` or `size` in
  it wins over the environment (`RETRO_HUD_CREATURE=0` still turns the
  creature off).
- Click menu: **size ▸** (tiny / big / tall) writes `size` for the
  session; **reroll** writes a new random `seed` and shows `pin it with
  RETRO_HUD_CREATURE_SEED=<n>`; **sprite ▸** offers the families while
  the creature is on.

### Notes
- The creature appears wherever the alien did, gauge-only mode included.
- Nothing can be drawn inside Claude Code's input box: the status line
  owns only its own lines.
- `MOOD_COLORS` now only colours the 2.x text-art sets.

## [v2.9.0] — 2026-10-22

### Changed
- The alien no longer narrates by default: `RETRO_HUD_BUBBLES=alerts` keeps
  only `need you` / `compact?` / `limit soon` and events-channel messages;
  `all` restores `ready`, `hm.`, `z`/`zZ` and idle quips; `off` silences it.
- Duration and cost share one row-2 field that alternates every 30s
  (`T:1h29m` ↔ `$40.86`), padded to the wider label so the flip moves
  nothing. `RETRO_HUD_COST_MODE=both` restores the two segments. The
  narrow-terminal ladder still shows the cost alone.

### Added
- **Agent presence.** The alien on the top rule now follows the agent
  running in the session, not just the gauges. It hustles while the agent
  works (`/o.o/`), waves when the turn is yours (`\^.^/`), beckons at a
  pending permission prompt (`/o.o?`), flinches at a burst of tool errors
  (`/>.<\`: two or more within 60s, held 30s), then dozes (`/-_-\`, after
  10 min) and sleeps (`/_._\`, after 60 min). Mood precedence: red-zone
  gauge → error → amber-zone gauge → what the agent is doing → calm.
- The state comes from a bounded tail of the session transcript (64 KB,
  widened once to 1 MB when a single huge entry hides every message).
  Only entry type, stop reason, error flag and timestamp are read, never
  message text. Meta entries and harness markers (`<command-name>`, …)
  don't count as the user; `[Request interrupted` hands the turn back.
- `presence-hook.sh` and `install.sh --hooks`: optional Claude Code hooks
  (`Stop`, `UserPromptSubmit`, `Notification` for `permission_prompt` /
  `idle_prompt`) that log what the transcript can't show, above all a
  pending permission prompt (the new `needs` state). When a hook's report
  is newer than the transcript, it wins. The merge into `settings.json`
  makes a backup, is idempotent, and leaves other hooks untouched;
  `uninstall.sh` removes the hooks again.
- Speech bubbles of up to 18 characters on the rule beside the sprite.
  Sources, in priority order: an **events channel**
  (`~/.cache/retro-hud/<session_id>.events.jsonl`, one
  `{"ts", "text", "ttl"}` per line, which any local tool may append to);
  state changes, once per transition (`ready`, `need you`, `hm.`,
  `compact?`, `limit soon`); and rare idle quips. A bubble only takes
  rule cells, so the frame never shifts.
- A per-session state file (`<session_id>.state.json`, written
  atomically) remembers transitions and keeps a snapshot (state, since,
  context %, worst limit %, cost). It honours `mute_until` and `sprite`
  set by other tools. Files untouched for 7 days are pruned. A write
  failure means no bubbles, never a broken bar.
- Sprite sets: `RETRO_HUD_SPRITE=alien|cat|robot|ghost`, every mood two
  frames at width 5.
- **Click the alien** (with `RETRO_HUD_ACTIONS=1` in tmux): the sprite,
  not its bubble, links to `retro-hud://agent`, and the reference
  handler shows a menu: `wave` (appends a 10s `wave` event), `quiet 1h`
  (sets `mute_until`), `sprite ▸` (alien / cat / robot / ghost, or
  `default` to drop the override) and `status` (the state file's
  snapshot as a tmux message). Edits to the state file are atomic and
  keep every other key. The handler checks the active-pane and `claude`
  rules as for the other actions and finds the session through
  `<cache>/pane-<N>.sid`, which the HUD writes while click actions are
  on. It reads `RETRO_HUD_AGENT_NAME` (menu title) and
  `RETRO_HUD_CACHE_DIR` from its environment or `~/.config/retro-hud/env`.
- An events-channel line with the text `wave` makes the sprite wave in
  place for its `ttl` instead of showing a bubble.
- Knobs: `RETRO_HUD_PRESENCE=0` (gauge-only alien, as before),
  `RETRO_HUD_AGENT_NAME`, `RETRO_HUD_QUIPS=0`, `RETRO_HUD_IDLE_MIN`,
  `RETRO_HUD_SLEEP_MIN`, `RETRO_HUD_CACHE_DIR`.

### Notes
- Presence is on by default. Rows 1 and 2 are unchanged; only the top
  rule redraws. With no transcript (or presence off) the output is
  byte-identical to v2.7.0.
- Without the hooks, a pending permission prompt reads as "working".
- `statusLine.refreshInterval` is required for idle/asleep and for
  bubbles to expire.

## [v2.8.0] — 2026-10-22

### Added
- **Click actions** (`RETRO_HUD_ACTIONS=1`, off by default). Inside tmux
  the model name, effort dot, context gauge, `$` cost and `+N/-M` lines
  become `retro-hud://` links, and the rate-limit gauges link to
  `retro-hud://usage` everywhere. With the reference handler a click pops
  a tmux menu and types the pick into that session's composer: `/model`,
  `/effort`, `/compact` · `/context` · `/clear` (behind a confirm menu),
  `/cost`; the lines open a read-only `git diff` popup and the gauges
  open your usage page. Off, or with any other value, the output is
  byte-identical to v2.7.0.
- URL contract `retro-hud://<action>?pane=<id>[&sock=<socket>]` (plus
  `cur=<level>` on `effort`), documented in the README so you can write
  your own handler. Links never carry a directory.
- `handler/retro-hud-handler.sh`, the reference handler (bash, Linux,
  tmux): strict URL whitelist and value validation; acts only on the
  clicking client's active pane while it runs `claude`; types with
  `send-keys -l`; menu items re-enter the handler with validated tokens
  only; the diff runs in the pane's own directory (from tmux) with git's
  config-driven programs disabled and `less` in secure mode; rejected
  clicks are logged to `~/.cache/retro-hud/handler.log`. Settings
  (`RETRO_HUD_MODELS`, `RETRO_HUD_USAGE_URL`) come from the environment
  or `~/.config/retro-hud/env`, read line by line and never sourced. An
  optional `~/.claude/retro-hud-handler.local.sh` is sourced first for
  your own actions.
- `install.sh --handler` / `--handler-only`: install the handler, create
  the settings file with commented defaults, and register the scheme via
  `xdg-mime` only when nothing owns it yet (otherwise report the owner).
  `uninstall.sh` removes the handler and, if it wrote it, the
  registration; your settings file is kept.

## [v2.7.0] — 2026-10-22

### Added
- `RETRO_HUD_HOME_URL`: when set, row 2 ends with a neon-green `⌂`
  hyperlinked (OSC 8) to that URL — a jump-home link for multi-session
  setups. Point it at any URL your desktop can open, e.g. a custom scheme
  that switches tmux sessions. It is one cell, always the last segment of
  row 2, and never dropped by the width-degradation ladder. Control
  characters in the URL are stripped so it cannot break out of the link.
  Unset or empty, the output is byte-identical to v2.6.0.

### Fixed
- The right edge of the frame (`─┐` / `─┘`) could be replaced by `…`.
  Claude Code draws the status line inside its prompt footer, which pads
  2 columns on each side, so the box is `COLUMNS − 4` wide; rows rendered
  at `COLUMNS − 3` overflowed it by one cell and were cut. The default
  `RETRO_HUD_MARGIN` is now `4`. Glyph widths were ruled out: Claude
  Code measures rows with the same widths the HUD uses.

### Notes
- Claude Code does not re-run the status line on a terminal resize; the
  previous output stays on screen until the next `refreshInterval` tick,
  so a `…` (after narrowing) or a short frame (after widening) can show
  for a few seconds. The troubleshooting guide now documents this and its
  mitigations (a shorter `refreshInterval`, a larger margin).
- If you set `statusLine.padding`, add twice that value to the margin.

## [v2.6.0] — 2026-09-15

### Changed
- A rate-limit gauge that reaches the amber zone now **stops rotating for
  good** and pins both numbers, instead of alternating `77%` ↔ `20h30m`.
  Rotation is fine while a limit is calm, but once it warns you want to
  read the pressure and the reset in one glance, without waiting out a
  flip.
- The pin threshold (`RETRO_HUD_COUNTDOWN_PCT`) now defaults to `70`,
  down from `75`, so it lines up with the amber zone. There is no longer
  a 70–74% window where the gauge is coloured as a warning but the label
  is still rotating.
- The five-hour label is mirrored to `20h30m · 77%`, so on both halves of
  the mirrored gauge the % is the token touching its own bar:
  `20h30m · 77% ▎███|███▊ 77% · 20h30m`.
- The pinned label is now the **last** thing row 2 gives up as the
  terminal narrows — it moved from step 2 to the end of the degradation
  ladder, behind the cache readout, token counts, diff stat, agent name,
  and session duration. Previously an ~100-column terminal silently
  reverted to rotating even at 95%, so a resize could change the mode.
  Below the amber zone this reordering has no effect.

### Notes
- `RED_CYCLE_S` (the 10s red-zone flip from v2.5.0) is retained but is now
  reachable only when rotation survives in the red zone — an extremely
  cramped row, or a raised `RETRO_HUD_COUNTDOWN_PCT`.
- Each gauge still escalates independently: a calm limit keeps cycling
  beside a warning one, and the existing `flex` padding keeps the centre
  divider fixed across those flips.

## [v2.5.0] — 2026-09-05

### Changed
- Red-zone rate-limit labels (≥ 90%) no longer collapse to the reset
  countdown alone: the % stays visible, either as the combined
  `95% · 2h` label or, when the row is too narrow for it, by continuing
  to cycle `95%` ↔ `2h` every 30s. Dropping the % hid the one number that
  matters most when you are about to hit 100%. `RETRO_HUD_RL_MODE=both`
  is unchanged; its red-zone opt-out is now simply the default.
- Red-zone labels that cycle do so every 10s instead of 30s, so urgency
  reads as tempo. Each gauge keeps its own clock: a 95% five-hour limit
  flips fast while a calm seven-day limit keeps the 30s beat.

## [v2.4.3] — 2026-07-08

### Changed
- Documentation finalized for release: README rebuilt around a real
  in-session screenshot with badges, segment tables (with visibility
  conditions), the rate-limit escalation ladder, and the alien's mood
  table; configuration, manual install, and the WSL2/VS Code width
  troubleshooting guide moved to `docs/configuration.md`.
- LICENSE copyright notice completed with the holder's name.

## [v2.4.2] — 2026-07-08

### Changed
- Cycling rate-limit labels are tight again — the fixed 5-column slot
  from v2.4.1 read as dead space in the % phase. Instead, each gauge now
  stretches to absorb its own label's phase width difference: the
  segment footprint, the center divider, and everything after it stay
  put across flips, with the slack rendered as gauge trough rather than
  blanks.

## [v2.4.1] — 2026-07-08

### Fixed
- Cycling rate-limit labels now reserve a fixed 5-column slot instead of
  padding to the current labels' max, so the blank space is identical in
  every phase and the row never reflows as countdown text lengthens or
  shrinks (`2h` vs `1h59m`).

### Changed
- Installer default `refreshInterval` lowered 30s → 5s so the frame
  re-fits within seconds of a terminal resize (Claude Code doesn't
  re-run the statusline on resize). Countdown flips stay on a 30s cycle.
- The alien now walks on a 10s tick, making the faster refresh visible.

## [v2.4.0] — 2026-07-08

### Changed
- The alien is now colored ASCII text art instead of emoji — `/o.o\`,
  `>o.o<`, `\o.o/` by mood, tinted green/amber/red, blinking every tick.
  Pure ASCII is width-exact in every terminal, which emoji are not.
- Rows now render `RETRO_HUD_MARGIN` (default 3) columns short of
  `$COLUMNS`: Claude Code's renderer truncates full-width lines with an
  ellipsis at an undocumented threshold (anthropics/claude-code#36417).
- Context token readout is contextual (`RETRO_HUD_CTX_TOKENS=auto`):
  hidden while the gauge is calm, shown from the amber zone up.
- Cycling rate-limit labels pad to a stable width so the row no longer
  reflows when the cycle flips between `%` and countdown.
- Session names are capped at 28 columns — Claude Code auto-generates
  long descriptive names that would otherwise dominate row 1.
- The xhigh effort glyph is now `◉` (was `⬤`, which many fonts draw
  double-width and misalign).

### Added
- `RETRO_HUD_WIDTH` (hard width override) and `RETRO_HUD_EMOJI`
  (`1` = count emoji as one cell, `0` = skip the folder emoji) for
  terminals whose width accounting disagrees with Unicode — see the new
  README troubleshooting section for WSL2/VS Code.

## [v2.3.0] — 2026-07-08

### Added
- A resident alien 👾 patrols the top frame rule, moving one step per
  30s refresh tick. It reacts to the worst gauge (context or either rate
  limit): past 70% it turns 👽 and doubles speed; in the red zone the
  mothership 🛸 arrives at 4× speed. Disable with `RETRO_HUD_ALIEN=0`.

## [v2.2.0] — 2026-07-08

### Changed
- Rate-limit labels now escalate per window: calm → cycling % ↔ time
  (v2.1.0 behavior), ≥75% → combined `81% · 3d`, red zone (≥90%) →
  time-to-reset only, since the gauge itself already shows saturation.
  `RETRO_HUD_RL_MODE=both` opts out of the red-zone override.

## [v2.1.0] — 2026-07-08

### Added
- Rate-limit labels now cycle between usage `%` and time-to-reset every
  30 seconds (pairs with the installer's `refreshInterval`). Above the
  countdown threshold both are shown together. Pin a style with
  `RETRO_HUD_RL_MODE=pct|time|both` (default `cycle`).

### Fixed
- README screenshot: emoji are now pinned to the character grid in the
  render pipeline, so the frame's right-edge corners align.

## [v2.0.0] — 2026-07-08

### Added
- Full HUD wireframe: rows now close with `─┐` / `─┘` at the right edge,
  joined by a dim rule (disable with `RETRO_HUD_FRAME=0`).
- Zoned context gauge: green / amber / red zones are tinted into the empty
  track like a redlined instrument, and the fill ramps through them.
- PR badge (`#42✓`) colored by review state (approved / pending /
  changes requested / draft), hyperlinked to the PR — uses the native `pr.*`
  statusline fields.
- Effort-level dot inside the model box (`· • ● ⬤ ✦` for
  low/medium/high/xhigh/max) and a `✧` thinking-enabled indicator — the
  effort display promised in the 1.x README now actually exists.
- Vim mode badge (`[N]` / `[I]` / `[V]`) when vim mode is on.
- Session name display (`◈ name`) on wide terminals.
- Lines added/removed (`+128/-37`) in row 2.
- Prompt-cache hit-rate readout (`cache 94%`) on very wide terminals.
- Context tokens next to the gauge (`42% 84.2K/200K`), window-size aware
  (200K vs 1M models).
- `--version` and `--demo` flags; `RETRO_HUD_COUNTDOWN_PCT` to tune when
  rate-limit reset countdowns appear (default 75%).
- Test suite (`python3 tests.py`) covering width safety at 50–240 columns,
  hostile payloads, and CLI behavior.

### Changed
- Git branch/remote detection now reads `.git/HEAD` and `.git/config`
  directly — no subprocess, no PATH dependency, no cache file, works in
  linked worktrees and on detached HEADs.
- Repository link prefers the native `workspace.repo` field when present.
- Gauges scale with terminal width (context 4–10 cells, rate limits 3–6)
  instead of the fixed 2-cell bars.
- Both rows degrade progressively (drop/truncate segments in priority
  order) and are guaranteed never to exceed the terminal width.
- Installer backs up `settings.json`, checks for `python3`, and sets
  `refreshInterval` so countdowns tick while idle.

### Removed
- The I/O token ratio bar. Claude Code v2.1.132 changed
  `total_input/output_tokens` to mean *current context*, not session
  totals, so the bar no longer measured what it claimed. Context tokens
  are now shown next to the context gauge instead.
- The 30-second git cache file (`~/.claude/.statusline_cache.json`) —
  obsolete now that git state is read directly from files.

### Fixed
- Rate-limit gauges are hidden entirely when `rate_limits` is absent
  (API-key users, free plans) instead of rendering a misleading `0% | 0%`.
- Malformed, empty, or type-mangled JSON on stdin renders a degraded HUD
  instead of a Python traceback.
- Percentages over 100 no longer overflow the gauge cells.
- Truncation now counts double-width characters correctly.

## [1.3] — 2026-05

- Fixed second-block rendering bug in the 5h usage bar.
- Rate-limit reset countdowns next to bars, gated at 75% usage.
- Slimmer row 2 with unified bar widths.

## [1.2] — 2026-05

- Row 2 overhaul: fractional-block bars, mirrored 5h/7d rate-limit
  gauges, I/O token bar.
- Python <3.12 compatibility fixes.

## [1.1] — 2026-04

- README polish.

## [1.0] — 2026-04

- Initial release: two-row retro sci-fi HUD with model box, directory,
  git branch badge with GitHub link, context bar, cost and duration.
