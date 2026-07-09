# Changelog

All notable changes to retro-hud are documented here.
Versioning follows [Semantic Versioning](https://semver.org) with `v`-prefixed
tags from v2.0.0 onward (earlier releases were tagged `1.0`–`1.3`).

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
