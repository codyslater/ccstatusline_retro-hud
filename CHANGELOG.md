# Changelog

All notable changes to retro-hud are documented here.
Versioning follows [Semantic Versioning](https://semver.org) with `v`-prefixed
tags from v2.0.0 onward (earlier releases were tagged `1.0`–`1.3`).

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
