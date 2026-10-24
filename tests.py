#!/usr/bin/env python3
"""retro-hud test suite — stdlib only. Run: python3 tests.py"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

# Presence knobs from the caller's shell must not leak into the suite (the
# CLI tests inherit os.environ), and nothing may touch the real cache dir.
for _k in ("RETRO_HUD_PRESENCE", "RETRO_HUD_SPRITE", "RETRO_HUD_AGENT_NAME",
           "RETRO_HUD_QUIPS", "RETRO_HUD_IDLE_MIN", "RETRO_HUD_SLEEP_MIN",
           "RETRO_HUD_ALIEN", "RETRO_HUD_CREATURE_SEED", "RETRO_HUD_CREATURE_COLOR",
           "RETRO_HUD_TICK_S"):
    os.environ.pop(_k, None)
# The 2.x suite pins the two-row HUD: RETRO_HUD_CREATURE=0 must stay
# byte-identical to it. Creature tests switch it on (CreatureCase).
os.environ["RETRO_HUD_CREATURE"] = "0"
# Excursions would make a creature test depend on the minute it runs in;
# ExcursionCase switches them on.
os.environ["RETRO_HUD_EXCURSIONS"] = "0"
_SUITE_TMP = tempfile.mkdtemp(prefix="retro-hud-tests-")
os.environ["RETRO_HUD_CACHE_DIR"] = os.path.join(_SUITE_TMP, "cache")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import statusline as sl

# Click actions are opt-in; a developer's own shell may export the toggle
# (and usually runs inside tmux), so every test starts from "off".
os.environ.pop("RETRO_HUD_ACTIONS", None)
# The golden fixtures below predate the single duration↔cost field; they are
# recorded in `both` mode. TestCostCycle sets `cycle` explicitly.
os.environ["RETRO_HUD_COST_MODE"] = "both"
# The presence tests below were written for the full narration; the default
# is now `alerts`. TestBubbleModes covers the default and `off`.
os.environ["RETRO_HUD_BUBBLES"] = "all"

NOW = 1_800_000_000


def iso(t):
    """Transcript-style ISO timestamp for epoch t."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(int(t))) + \
        ".{:03d}Z".format(int(round((t - int(t)) * 1000)))


def asst(t, stop="end_turn", blocks=("text",)):
    return {"type": "assistant", "timestamp": iso(t),
            "message": {"role": "assistant", "stop_reason": stop,
                        "content": [{"type": b} for b in blocks]}}


def user(t, text="do the thing", meta=False):
    e = {"type": "user", "timestamp": iso(t),
         "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
    if meta:
        e["isMeta"] = True
    return e


def result(t, is_error=False):
    return {"type": "user", "timestamp": iso(t),
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "x", "is_error": is_error,
                 "content": "..."}]}}

FULL = {
    "model": {"display_name": "Fable 5"},
    "workspace": {"current_dir": "/home/u/projects/some-long-project-name",
                  "repo": {"host": "github.com", "owner": "u", "name": "p"}},
    "session_name": "my-session",
    "effort": {"level": "high"},
    "thinking": {"enabled": True},
    "vim": {"mode": "INSERT"},
    "context_window": {"used_percentage": 72, "total_input_tokens": 144213,
                       "context_window_size": 200000,
                       "current_usage": {"input_tokens": 2900,
                                         "cache_read_input_tokens": 137300,
                                         "cache_creation_input_tokens": 4013,
                                         "output_tokens": 1150}},
    "cost": {"total_cost_usd": 3.21, "total_duration_ms": 5432100,
             "total_lines_added": 128, "total_lines_removed": 37},
    "pr": {"number": 42, "url": "https://github.com/u/p/pull/42",
           "review_state": "approved"},
    "agent": {"name": "reviewer"},
    "rate_limits": {"five_hour": {"used_percentage": 63, "resets_at": NOW + 7200},
                    "seven_day": {"used_percentage": 81, "resets_at": NOW + 259200}},
}

MINIMAL = {"model": {"display_name": "X"}, "workspace": {"current_dir": "/tmp"}}

OVERLOAD = {
    "model": {"display_name": "A Very Long Model Display Name Indeed"},
    "workspace": {"current_dir": "/x/" + "deeply-nested-directory-name" * 3},
    "context_window": {"used_percentage": 130, "total_input_tokens": 99999999},
    "cost": {"total_cost_usd": 1234.5678, "total_duration_ms": 999999999,
             "total_lines_added": 99999, "total_lines_removed": 88888},
    "rate_limits": {"five_hour": {"used_percentage": 250, "resets_at": NOW + 60},
                    "seven_day": {"used_percentage": -5, "resets_at": NOW - 100}},
}


class TestWidth(unittest.TestCase):
    """No row may ever exceed the terminal width."""

    def test_fits_all_widths_and_payloads(self):
        for payload in (FULL, MINIMAL, OVERLOAD, {}):
            for cols in range(50, 241, 10):
                rows = sl.render(copy.deepcopy(payload), cols, NOW)
                for i, row in enumerate(rows):
                    w = sl.vislen(row)
                    self.assertLessEqual(
                        w, cols,
                        "row{} overflows at cols={} ({} > {}): {!r}".format(
                            i + 1, cols, w, cols, sl.strip_ansi(row)))

    def test_frame_fills_to_edge(self):
        rows = sl.render(copy.deepcopy(FULL), 160, NOW)
        for row in rows:
            self.assertEqual(sl.vislen(row), 160)
        self.assertTrue(sl.strip_ansi(rows[0]).endswith("┐"))
        self.assertTrue(sl.strip_ansi(rows[1]).endswith("┘"))

    def test_frame_disabled_by_env(self):
        os.environ["RETRO_HUD_FRAME"] = "0"
        try:
            rows = sl.render(copy.deepcopy(FULL), 160, NOW)
            self.assertFalse(sl.strip_ansi(rows[0]).endswith("┐"))
        finally:
            del os.environ["RETRO_HUD_FRAME"]


class TestContent(unittest.TestCase):
    def test_full_payload_segments(self):
        plain = "\n".join(sl.strip_ansi(r) for r in sl.render(copy.deepcopy(FULL), 220, NOW))
        for expect in ("Fable 5", "●", "✧", "some-long-project-name", "#42✓",
                       "[I]", "◈ my-session", "72%", "144.2K/200K", "63%", "81%",
                       "· 3d", "+128", "-37", "cache 95%", "2h", "$3.2",
                       "▐█ reviewer"):
            self.assertIn(expect, plain, "missing {!r} in:\n{}".format(expect, plain))

    def test_ctx_tokens_auto_hides_when_calm(self):
        calm = copy.deepcopy(FULL)
        calm["context_window"]["used_percentage"] = 42
        plain = sl.strip_ansi(sl.render(calm, 220, NOW)[1])
        self.assertNotIn("144.2K", plain)   # auto: hidden below amber zone
        os.environ["RETRO_HUD_CTX_TOKENS"] = "always"
        try:
            plain = sl.strip_ansi(sl.render(copy.deepcopy(calm), 220, NOW)[1])
            self.assertIn("144.2K/200K", plain)
        finally:
            del os.environ["RETRO_HUD_CTX_TOKENS"]

    def test_session_name_capped(self):
        longname = copy.deepcopy(FULL)
        longname["session_name"] = "Polish HUD design and prepare production release"
        plain = sl.strip_ansi(sl.render(longname, 220, NOW)[0])
        self.assertIn("◈ Polish HUD design and prep..", plain)

    def test_countdown_gated_below_threshold(self):
        # NOW // 30 is even → percentage phase of the cycle
        plain = sl.strip_ansi(sl.render(copy.deepcopy(FULL), 220, NOW)[1])
        self.assertIn("63%", plain)
        self.assertNotIn("63% ·", plain)  # 63 < 70 → no combined label
        self.assertIn("81% ·", plain)     # ≥70 → both, in every phase

    def test_cycle_time_phase(self):
        # NOW+30 // 30 is odd → time phase: 5h label becomes a countdown
        plain = sl.strip_ansi(sl.render(copy.deepcopy(FULL), 220, NOW + 30)[1])
        self.assertIn("1h59m", plain)     # 7200s reset − 30s elapsed
        self.assertNotIn("63%", plain)
        self.assertIn("81% ·", plain)     # urgent side still shows both

    def test_warning_zone_pins_both_labels(self):
        # 70% is where the gauge turns amber — the label pins there too,
        # in every cycle phase, instead of rotating until 75%.
        warm = copy.deepcopy(FULL)
        warm["rate_limits"]["seven_day"]["used_percentage"] = 70
        for t in (NOW, NOW + 30):
            plain = sl.strip_ansi(sl.render(copy.deepcopy(warm), 220, t)[1])
            self.assertIn("70% · ", plain)

    def test_just_below_warning_still_cycles(self):
        # 69% is the last rung that rotates — the pin is tied to the amber
        # zone, not to a rounder number.
        cool = copy.deepcopy(FULL)
        cool["rate_limits"]["seven_day"]["used_percentage"] = 69
        del cool["context_window"]["current_usage"]
        pct_row = sl.strip_ansi(sl.render(copy.deepcopy(cool), 220, NOW)[1])
        time_row = sl.strip_ansi(sl.render(copy.deepcopy(cool), 220, NOW + 30)[1])
        self.assertIn("69%", pct_row)
        self.assertNotIn("69% ·", pct_row)
        self.assertNotIn("69%", time_row)

    def test_five_hour_label_mirrors_pct_toward_bar(self):
        # The mirror seats each % against the center divider: the 5h label
        # reads "2h · 95%" so its % touches its own bar, matching the way
        # the 7d side's "81% · 3d" touches its own.
        hot = copy.deepcopy(FULL)
        hot["rate_limits"]["five_hour"]["used_percentage"] = 95
        del hot["context_window"]["current_usage"]  # no "cache 95%" collision
        plain = sl.strip_ansi(sl.render(hot, 220, NOW)[1])
        self.assertIn("2h · 95% ", plain)
        self.assertNotIn("95% · 2h", plain)
        self.assertIn("81% · 3d", plain)

    def test_red_zone_keeps_pct_beside_countdown(self):
        # ≥ 90% never hides the %: the combined label pins in both phases,
        # exactly like the 70–89% rung.
        hot = copy.deepcopy(FULL)
        hot["rate_limits"]["five_hour"]["used_percentage"] = 95
        del hot["context_window"]["current_usage"]
        pct_row = sl.strip_ansi(sl.render(copy.deepcopy(hot), 220, NOW)[1])
        time_row = sl.strip_ansi(sl.render(copy.deepcopy(hot), 220, NOW + 30)[1])
        self.assertIn("2h · 95%", pct_row)
        self.assertIn("1h59m · 95%", time_row)

    def test_warning_labels_survive_a_narrow_row(self):
        # The combined label is the last thing row 2 gives up: at 80
        # columns the agent and the duration go first, and both numbers
        # stay pinned in every phase.
        hot = copy.deepcopy(FULL)
        hot["rate_limits"]["five_hour"]["used_percentage"] = 95
        del hot["context_window"]["current_usage"]
        for t in (NOW, NOW + 10, NOW + 30):
            plain = sl.strip_ansi(sl.render(copy.deepcopy(hot), 80, t)[1])
            self.assertRegex(plain, r"\dh(\d+m)? · 95%")

    def test_red_zone_cycles_faster_when_pinning_is_off(self):
        # RED_CYCLE_S still governs any row that does rotate in the red
        # zone — raise the threshold past 95 and the 5h side flips on the
        # 10s clock while the 81% side is still on its 30s one.
        os.environ["RETRO_HUD_COUNTDOWN_PCT"] = "99"
        try:
            hot = copy.deepcopy(FULL)
            hot["rate_limits"]["five_hour"]["used_percentage"] = 95
            del hot["context_window"]["current_usage"]
            row = sl.strip_ansi(sl.render(hot, 220, NOW + 10)[1])
            self.assertIn("1h59m", row)
            self.assertNotIn("95%", row)
            self.assertIn(" 81% ", row)
            self.assertNotIn("81% ·", row)
        finally:
            del os.environ["RETRO_HUD_COUNTDOWN_PCT"]

    def test_cycle_labels_tight_and_gauges_flex(self):
        # Cycling labels carry no padding blanks — instead each gauge
        # stretches to absorb its label's phase width difference, so the
        # segment footprint is identical in both phases.
        payload = copy.deepcopy(FULL)
        payload["rate_limits"] = {
            "five_hour": {"used_percentage": 35, "resets_at": NOW + 9930},
            "seven_day": {"used_percentage": 9, "resets_at": NOW + 536400}}
        pct_row = sl.strip_ansi(sl.render(copy.deepcopy(payload), 220, NOW)[1])
        time_row = sl.strip_ansi(sl.render(copy.deepcopy(payload), 220, NOW + 30)[1])
        self.assertIn("// 35%", pct_row)                 # tight after separator
        self.assertIsNone(re.search(r"//\s{2,}35%", pct_row))
        self.assertIsNone(re.search(r"9%\s{2,}//", pct_row))
        self.assertIn("// " + sl.fmt_countdown(9900), time_row)
        # constant footprint: with the frame off, both phases are equal
        # width, and the divider sits at the same column
        os.environ["RETRO_HUD_FRAME"] = "0"
        try:
            p = sl.strip_ansi(sl.render(copy.deepcopy(payload), 220, NOW)[1])
            t = sl.strip_ansi(sl.render(copy.deepcopy(payload), 220, NOW + 30)[1])
            self.assertEqual(sl.vwidth(p), sl.vwidth(t))
            self.assertEqual(p.index("|"), t.index("|"))
        finally:
            del os.environ["RETRO_HUD_FRAME"]

    def test_rl_mode_env_pins_phase(self):
        os.environ["RETRO_HUD_RL_MODE"] = "pct"
        try:
            plain = sl.strip_ansi(sl.render(copy.deepcopy(FULL), 220, NOW + 30)[1])
            self.assertIn("63%", plain)   # pinned to pct despite time phase
        finally:
            del os.environ["RETRO_HUD_RL_MODE"]

    def test_no_rate_limits_hides_mirror(self):
        plain = sl.strip_ansi(sl.render(copy.deepcopy(MINIMAL), 160, NOW)[1])
        self.assertNotIn("|", plain)
        self.assertEqual(plain.count("%"), 1)  # only the context gauge

    def test_percentages_clamped(self):
        rows = sl.render(copy.deepcopy(OVERLOAD), 200, NOW)
        plain = sl.strip_ansi(rows[1])
        self.assertIn("130%", plain)  # label shows truth
        self.assertLessEqual(sl.vislen(rows[1]), 200)  # gauge stays in bounds

    def test_empty_payload_renders(self):
        rows = sl.render({}, 100, NOW)
        self.assertEqual(len(rows), 2)
        self.assertIn("---", sl.strip_ansi(rows[0]))


class TestAlien(unittest.TestCase):
    def test_mood_escalates_with_worst_gauge(self):
        # NOW tick is even → first blink frame of each mood
        # FULL: worst gauge is 7d at 81% → agitated
        self.assertIn(">o.o<", sl.strip_ansi(sl.render(copy.deepcopy(FULL), 200, NOW)[0]))
        # MINIMAL: everything at 0 → calm
        self.assertIn("/o.o\\", sl.strip_ansi(sl.render(copy.deepcopy(MINIMAL), 200, NOW)[0]))
        # OVERLOAD: rate limit at 250% → red zone, arms up
        self.assertIn("\\o.o/", sl.strip_ansi(sl.render(copy.deepcopy(OVERLOAD), 200, NOW)[0]))

    def test_alien_patrols_and_blinks(self):
        r1 = sl.render(copy.deepcopy(MINIMAL), 200, NOW)[0]
        r2 = sl.render(copy.deepcopy(MINIMAL), 200, NOW + 30)[0]
        self.assertNotEqual(r1, r2)                     # it moved
        self.assertIn("/-.-\\", sl.strip_ansi(r2))      # odd tick → blink frame
        self.assertEqual(sl.vislen(r1), sl.vislen(r2))  # width unchanged
        self.assertEqual(sl.vislen(r1), 200)

    def test_alien_disabled_by_env(self):
        os.environ["RETRO_HUD_ALIEN"] = "0"
        try:
            plain = sl.strip_ansi(sl.render(copy.deepcopy(MINIMAL), 200, NOW)[0])
            self.assertNotIn("o.o", plain)
            self.assertTrue(plain.endswith("┐"))  # frame still closes
        finally:
            del os.environ["RETRO_HUD_ALIEN"]

    def test_alien_skipped_on_short_track(self):
        # A narrow terminal leaves no rule to patrol — no crash, no alien
        plain = sl.strip_ansi(sl.render(copy.deepcopy(FULL), 60, NOW)[0])
        self.assertNotIn("o.o", plain)

    def test_emoji_knob(self):
        os.environ["RETRO_HUD_EMOJI"] = "0"
        try:
            plain = sl.strip_ansi(sl.render(copy.deepcopy(FULL), 200, NOW)[0])
            self.assertNotIn("\U0001F4C2", plain)  # folder icon dropped
        finally:
            del os.environ["RETRO_HUD_EMOJI"]
        os.environ["RETRO_HUD_EMOJI"] = "1"
        try:
            row = sl.render(copy.deepcopy(FULL), 200, NOW)[0]
            self.assertEqual(sl.vislen(row), 200)  # emoji counted as 1 cell
        finally:
            del os.environ["RETRO_HUD_EMOJI"]


class TestCostCycle(unittest.TestCase):
    """RETRO_HUD_COST_MODE=cycle: duration and cost share one padded field."""

    def setUp(self):
        self._saved = os.environ.get("RETRO_HUD_COST_MODE")
        os.environ["RETRO_HUD_COST_MODE"] = "cycle"

    def tearDown(self):
        os.environ.pop("RETRO_HUD_COST_MODE", None)
        if self._saved is not None:
            os.environ["RETRO_HUD_COST_MODE"] = self._saved

    def row2(self, now, cols=220):
        return sl.strip_ansi(sl.render(copy.deepcopy(FULL), cols, now)[1])

    def test_alternates_every_cycle(self):
        a = self.row2(NOW)
        b = self.row2(NOW + sl.CYCLE_S)
        self.assertNotEqual(a, b)
        shown = {("2h" in a, "$3.2" in a), ("2h" in b, "$3.2" in b)}
        self.assertEqual(shown, {(True, False), (False, True)})

    def test_flip_moves_nothing(self):
        # Without rate limits (whose countdown labels legitimately move with
        # time) the only thing changing between phases is this field.
        payload = copy.deepcopy(FULL)
        payload.pop("rate_limits", None)
        a = sl.strip_ansi(sl.render(copy.deepcopy(payload), 220, NOW)[1])
        b = sl.strip_ansi(sl.render(copy.deepcopy(payload), 220, NOW + sl.CYCLE_S)[1])
        self.assertNotEqual(a, b)
        self.assertEqual(len(a), len(b))               # the frame absorbs the difference
        # no padding (CS): separators after the field may shift by the two labels'
        # width difference ("2h" vs "$3.2": 2 cells), never more; those before it never
        sa = [m.start() for m in re.finditer("//", a)]
        sb = [m.start() for m in re.finditer("//", b)]
        self.assertEqual(len(sa), len(sb))
        self.assertTrue(all(abs(x - y) <= 2 for x, y in zip(sa, sb)), (sa, sb))
        self.assertEqual(sa[:3], sb[:3])
        self.assertEqual(a.index("┘"), b.index("┘"))

    def test_not_padded_the_separator_keeps_one_space(self):
        a = self.row2(NOW)
        b = self.row2(NOW + sl.CYCLE_S)
        short = a if "2h" in a else b
        self.assertIn("2h //", short)           # no padding: one space, then the separator
        self.assertNotIn("2h  ", short)

    def test_narrow_shows_cost_alone(self):
        row = self.row2(NOW, cols=44)   # the ladder has dropped the duration here
        self.assertIn("$3.2", row)
        self.assertNotIn("2h", row)

    def test_both_mode_keeps_two_segments(self):
        os.environ["RETRO_HUD_COST_MODE"] = "both"
        row = self.row2(NOW)
        self.assertIn("2h", row)
        self.assertIn("$3.2", row)
        self.assertLess(row.index("2h"), row.index("$3.2"))

    def test_cost_link_covers_the_field(self):
        os.environ["RETRO_HUD_ACTIONS"] = "1"
        os.environ["TMUX_PANE"] = "%3"
        try:
            for now in (NOW, NOW + sl.CYCLE_S):
                raw = sl.render(copy.deepcopy(FULL), 220, now)[1]
                self.assertEqual(raw.count("retro-hud://cost"), 1)
        finally:
            os.environ.pop("RETRO_HUD_ACTIONS", None)
            os.environ.pop("TMUX_PANE", None)


class TestWidthKnobs(unittest.TestCase):
    SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "statusline.py")

    def run_script(self, env_extra):
        env = dict(os.environ, COLUMNS="120")
        env.update(env_extra)
        return subprocess.run([sys.executable, self.SCRIPT], input=b"{}",
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env, timeout=10)

    def test_default_margin(self):
        out = self.run_script({}).stdout.decode()
        widths = [sl.vislen(line) for line in out.splitlines()]
        self.assertEqual(max(widths), 116)  # 120 − default margin 4

    def test_default_fits_claude_code_prompt_footer(self):
        # Claude Code's prompt footer pads its row by 2 columns on each side
        # (inline mode), so the status line box is COLUMNS − 4 wide. Any row
        # wider than that is cut by Ink's truncate and the frame's right
        # edge ("─┐" / "─┘") turns into "…".
        out = self.run_script({"RETRO_HUD_HOME_URL": ""}).stdout.decode()
        for line in out.splitlines():
            self.assertLessEqual(sl.vislen(line), 120 - 2 * 2, sl.strip_ansi(line))

    def test_margin_and_width_overrides(self):
        out = self.run_script({"RETRO_HUD_MARGIN": "5"}).stdout.decode()
        self.assertEqual(max(sl.vislen(l) for l in out.splitlines()), 115)
        out = self.run_script({"RETRO_HUD_WIDTH": "80",
                               "RETRO_HUD_MARGIN": "0"}).stdout.decode()
        self.assertEqual(max(sl.vislen(l) for l in out.splitlines()), 80)


class TestHomeLink(unittest.TestCase):
    URL = "example-home://jump?to=work"
    # sha256 of "\n".join(render(FULL, cols, NOW)) as rendered by v2.6.0,
    # before RETRO_HUD_HOME_URL existed: unset must stay byte-identical.
    GOLDEN = {
        60: "65f3666f428a782a2ab76a050b34db04917e99bd61de7a54763a23f731f500ea",
        100: "d3acb7d6d65223b2a764b81d37fed41d4815718edff60327f3e612ebe9cc758c",
        160: "18fbeeb20e697531f44114984381523b65b773a62b4b366e7c5cebde2506563e",
        220: "a72a0c0fb3fc0836a9181bc99a4c536b75a93d1be564ca58416716a328c4e11f",
    }

    def setUp(self):
        self._saved = os.environ.pop("RETRO_HUD_HOME_URL", None)

    def tearDown(self):
        os.environ.pop("RETRO_HUD_HOME_URL", None)
        if self._saved is not None:
            os.environ["RETRO_HUD_HOME_URL"] = self._saved

    def digest(self, cols):
        import hashlib
        rows = sl.render(copy.deepcopy(FULL), cols, NOW)
        return hashlib.sha256("\n".join(rows).encode()).hexdigest()

    def test_unset_is_byte_identical_to_previous_release(self):
        for cols, want in self.GOLDEN.items():
            self.assertEqual(self.digest(cols), want, "cols={}".format(cols))

    def test_empty_or_blank_counts_as_unset(self):
        for val in ("", "   "):
            os.environ["RETRO_HUD_HOME_URL"] = val
            for cols, want in self.GOLDEN.items():
                self.assertEqual(self.digest(cols), want, "val={!r}".format(val))

    def test_home_glyph_is_last_segment_of_row2(self):
        os.environ["RETRO_HUD_HOME_URL"] = self.URL
        rows = sl.render(copy.deepcopy(FULL), 220, NOW)
        self.assertIn("\x1b]8;;" + self.URL + "\a⌂\x1b]8;;\a", rows[1])
        plain = sl.strip_ansi(rows[1])
        self.assertRegex(plain, r"▐█ reviewer // ⌂ ─+┘$")
        self.assertNotIn("⌂", sl.strip_ansi(rows[0]))

    def test_home_glyph_survives_every_width(self):
        os.environ["RETRO_HUD_HOME_URL"] = self.URL
        for payload in (FULL, MINIMAL, OVERLOAD, {}):
            for cols in range(20, 241, 5):
                rows = sl.render(copy.deepcopy(payload), cols, NOW)
                self.assertIn("⌂", sl.strip_ansi(rows[1]), "cols={}".format(cols))
                if cols < 50:  # same floor as TestWidth's fit guarantee
                    continue
                for row in rows:
                    self.assertLessEqual(sl.vislen(row), cols, "cols={}".format(cols))

    def test_control_chars_in_url_cannot_escape_the_link(self):
        os.environ["RETRO_HUD_HOME_URL"] = "x://a\x07\x1b[31mb\nc"
        row = sl.render(copy.deepcopy(MINIMAL), 160, NOW)[1]
        self.assertIn("\x1b]8;;x://a[31mbc\a⌂", row)
        self.assertNotIn("\n", row)


class TestClickActionLinks(unittest.TestCase):
    """RETRO_HUD_ACTIONS=1 wraps segments in retro-hud:// OSC 8 links."""
    # sha256 of "\n".join(render(payload, cols, NOW)) as rendered by v2.7.0.
    # With actions off the output must stay byte-identical, even in tmux.
    GOLDEN = {
        "FULL": {
            60: "65f3666f428a782a2ab76a050b34db04917e99bd61de7a54763a23f731f500ea",
            100: "d3acb7d6d65223b2a764b81d37fed41d4815718edff60327f3e612ebe9cc758c",
            160: "18fbeeb20e697531f44114984381523b65b773a62b4b366e7c5cebde2506563e",
            220: "a72a0c0fb3fc0836a9181bc99a4c536b75a93d1be564ca58416716a328c4e11f"},
        "MINIMAL": {
            60: "2f1c609b861da918eb94de12c4d191e24f49ebcb96d9cb3378b9e90d27cc21ba",
            100: "5f69e6d3fd142bff9e82509678975d31d04309b529872f0d73769ee321f8ab71",
            160: "a2f4d74097b5f747bf76466ad2c1c2e1c2a1fad2acd72d12834eb462d72b9eb1",
            220: "eedd80df69f13df613892a0252c9e1ec48bed3e77024f020277fce6f81a1552e"},
        "OVERLOAD": {
            60: "b3f9c4feba599b52d802c000d49679dbc8046bd18bc341670b6853ae20c31068",
            100: "656d2d1c0d4b672db0ad0a20508b54e16d992f0d67d570a8c9a49b62c56baf9c",
            160: "5976a63b1722754fa944eb0409d6e61a874f50cf5a8c4aeacf6cccd15c702250",
            220: "7abe75b553a73407976fe3fd6ca3c1a3143e5cc3289a5034d602b4b274bb9e15"},
    }
    KEYS = ("RETRO_HUD_ACTIONS", "TMUX_PANE", "TMUX", "RETRO_HUD_HOME_URL")
    Q = "pane=%257&sock=/tmp/tmux-1000/default"

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in self.KEYS}

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def tmux_env(self):
        os.environ["TMUX_PANE"] = "%7"
        os.environ["TMUX"] = "/tmp/tmux-1000/default,4242,0"

    def digest(self, payload, cols):
        import hashlib
        rows = sl.render(copy.deepcopy(payload), cols, NOW)
        return hashlib.sha256("\n".join(rows).encode()).hexdigest()

    def check_golden(self):
        for name, table in self.GOLDEN.items():
            for cols, want in table.items():
                self.assertEqual(self.digest(globals()[name], cols), want,
                                 "{} cols={}".format(name, cols))

    def test_off_is_byte_identical_to_2_7_0(self):
        self.check_golden()

    def test_a_list_links_only_those_actions(self):
        os.environ.update({"RETRO_HUD_ACTIONS": "model,diff, card,bogus", "TMUX_PANE": "%7",
                           "TMUX": "/tmp/tmux-1000/default,1,0"})
        self.assertEqual(sl.actions_on(), {"model", "diff", "card"})
        rows = sl.render(copy.deepcopy(FULL), 220, NOW)
        found = {}
        for i, row in enumerate(rows):
            for m in re.finditer(r"\x1b\]8;;(retro-hud://([a-z]+)[^\x07]*)\x07", row):
                found.setdefault(m.group(2), []).append(i)
        self.assertEqual(set(found), {"model", "diff"} | ({"card"} if "card" in found else set()))
        os.environ["RETRO_HUD_ACTIONS"] = "bogus,,"
        self.assertIsNone(sl.actions_on())
        self.assertEqual(sl.render(copy.deepcopy(FULL), 220, NOW)[1].count("retro-hud://"), 0)
        self.assertIs(sl.actions_on() if os.environ.update({"RETRO_HUD_ACTIONS": "1"}) else sl.actions_on(), True)

    def test_off_inside_tmux_is_byte_identical(self):
        self.tmux_env()
        self.check_golden()
        for val in ("0", "", "yes", "true"):
            os.environ["RETRO_HUD_ACTIONS"] = val
            self.check_golden()

    def links(self, payload=FULL, cols=220):
        rows = sl.render(copy.deepcopy(payload), cols, NOW)
        found = {}
        for i, row in enumerate(rows):
            for url, text in re.findall(
                    r"\x1b\]8;;(retro-hud://[^\x07]*)\x07(.*?)\x1b\]8;;\x07", row):
                name = url.split("?")[0][len("retro-hud://"):]
                found.setdefault(name, []).append((i, url, sl.strip_ansi(text)))
        return found

    def test_segments_carry_links_inside_tmux(self):
        os.environ["RETRO_HUD_ACTIONS"] = "1"
        self.tmux_env()
        found = self.links()
        self.assertEqual(found["model"], [(0, "retro-hud://model?" + self.Q, "Fable 5")])
        self.assertEqual(found["effort"],
                         [(0, "retro-hud://effort?" + self.Q + "&cur=high", "●")])
        (row, url, text), = found["ctx"]
        self.assertEqual((row, url), (1, "retro-hud://ctx?" + self.Q))
        self.assertTrue(text.endswith("72%"), text)
        self.assertEqual(found["cost"], [(1, "retro-hud://cost?" + self.Q, "$3.2")])
        self.assertEqual(found["diff"], [(1, "retro-hud://diff?" + self.Q, "+128/-37")])
        (row, url, text), = found["usage"]
        self.assertEqual((row, url), (1, "retro-hud://usage?" + self.Q))
        self.assertIn("63%", text)
        self.assertIn("81% · 3d", text)
        (row, url, text), = found["card"]  # the alien on the top rule: its status card
        self.assertEqual((row, url), (0, "retro-hud://card?" + self.Q))
        self.assertIn(text, [f for pair in sl.ALIEN_FRAMES for f in pair])
        (row, url, text), = found["agent"]  # the session-name segment: the agent menu
        self.assertEqual((row, url), (0, "retro-hud://agent?" + self.Q))
        self.assertEqual(text, "◈ my-session")
        self.assertEqual(set(found),
                         {"model", "effort", "ctx", "cost", "diff", "usage", "agent", "card"})

    def test_branch_and_pr_keep_their_web_links(self):
        os.environ["RETRO_HUD_ACTIONS"] = "1"
        self.tmux_env()
        row = sl.render(copy.deepcopy(FULL), 220, NOW)[0]
        self.assertIn("\x1b]8;;https://github.com/u/p/pull/42\a#42✓", row)
        payload = copy.deepcopy(FULL)
        payload["_branch_override"] = "main"
        row = sl.render(payload, 220, NOW)[0]
        self.assertIn("\x1b]8;;https://github.com/u/p/tree/main\amain", row)

    def test_outside_tmux_only_usage_links(self):
        os.environ["RETRO_HUD_ACTIONS"] = "1"
        found = self.links()
        self.assertEqual(set(found), {"usage"})
        self.assertEqual(found["usage"][0][1], "retro-hud://usage")

    def test_malformed_pane_counts_as_outside_tmux(self):
        os.environ["RETRO_HUD_ACTIONS"] = "1"
        for pane in ("%7;x", "7", "%", "%7 ", ""):
            os.environ["TMUX_PANE"] = pane
            self.assertEqual(set(self.links()), {"usage"}, repr(pane))

    def test_no_sock_without_tmux_var(self):
        os.environ["RETRO_HUD_ACTIONS"] = "1"
        os.environ["TMUX_PANE"] = "%12"
        url = self.links()["cost"][0][1]
        self.assertEqual(url, "retro-hud://cost?pane=%2512")

    def test_links_never_carry_the_cwd(self):
        # The handler asks tmux for the pane's directory instead: a link
        # must not be able to point git at an arbitrary directory.
        os.environ["RETRO_HUD_ACTIONS"] = "1"
        os.environ["TMUX_PANE"] = "%1"
        os.environ["TMUX"] = "/tmp/my sock#1,1,0"
        payload = copy.deepcopy(FULL)
        payload["workspace"]["current_dir"] = "/tmp/a b&c=d#e?f%gé"
        for name, hits in self.links(payload).items():
            for _, url, _ in hits:
                self.assertNotIn("cwd", url)
                self.assertNotIn("/tmp/a", url)
                # the reference handler's whitelist accepts every URL the HUD emits
                self.assertRegex(url, r"^retro-hud://[a-z]+(\?[A-Za-z0-9_=&%.:/~+-]*)?$")
        self.assertEqual(self.links(payload)["cost"][0][1],
                         "retro-hud://cost?pane=%251&sock=/tmp/my%20sock%231")

    def test_effort_link_omits_unknown_level(self):
        os.environ["RETRO_HUD_ACTIONS"] = "1"
        os.environ["TMUX_PANE"] = "%1"
        payload = copy.deepcopy(FULL)
        payload["effort"]["level"] = "turbo"
        self.assertNotIn("effort", self.links(payload))

    def test_links_never_change_the_visible_rows(self):
        self.tmux_env()
        for payload in (FULL, MINIMAL, OVERLOAD, {}):
            for cols in range(50, 241, 10):
                os.environ["RETRO_HUD_ACTIONS"] = "0"
                plain = [sl.strip_ansi(r) for r in sl.render(copy.deepcopy(payload), cols, NOW)]
                os.environ["RETRO_HUD_ACTIONS"] = "1"
                linked = [sl.strip_ansi(r) for r in sl.render(copy.deepcopy(payload), cols, NOW)]
                self.assertEqual(plain, linked, "cols={}".format(cols))


# ── shell-side tests: the reference handler and the installer ──
# These run bash with a throwaway HOME and fake tmux / xdg-* commands, so
# nothing touches the real desktop, tmux server or ~/.config.
REPO = os.path.dirname(os.path.abspath(__file__))
HANDLER = os.path.join(REPO, "handler", "retro-hud-handler.sh")

FAKE_TMUX = r'''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
with open(os.path.join(os.environ["HOME"], "tmux.log"), "a") as f:
    f.write(json.dumps(argv) + "\n")
cmd = argv[2:] if argv[:1] == ["-S"] else argv
if os.environ.get("FAKE_TMUX_NOSERVER"):
    sys.stderr.write("no server running\n")
    sys.exit(1)
if cmd[:1] == ["list-clients"]:
    sys.stdout.write(os.environ.get("FAKE_TMUX_CLIENTS",
                     "100 /dev/pts/1\n300 /dev/pts/3\n200 /dev/pts/2\n"))
elif cmd[:1] in (["display"], ["display-message"]) and "-p" in cmd:
    answer = {"#{pane_current_command}": os.environ.get("FAKE_TMUX_PANE_CMD", "claude"),
              "#{pane_pid}": os.environ.get("FAKE_TMUX_PANE_PID", "1"),
              "#{pane_current_path}": os.environ.get("FAKE_TMUX_PANE_PATH", ""),
              "#{pane_id}": os.environ.get("FAKE_TMUX_ACTIVE_PANE", "%7")}
    sys.stdout.write(answer.get(cmd[-1], "") + "\n")
elif cmd[:1] == ["show-options"]:
    sys.stdout.write(os.environ.get("FAKE_TMUX_FEATURES", "") + "\n")
elif cmd[:1] == ["display-popup"]:
    import re, shutil
    m = re.fullmatch(r"bash '([^']+)'", cmd[-1])        # keep the popup's files: the handler removes them after
    if m and os.path.exists(m.group(1)):
        shutil.copy(m.group(1), os.path.join(os.environ["HOME"], "popup.runner"))
        card = re.search(r"cat '([^']+)'", open(m.group(1)).read())
        if card and os.path.exists(card.group(1)):
            shutil.copy(card.group(1), os.path.join(os.environ["HOME"], "popup.card"))
    if os.environ.get("FAKE_TMUX_POPUP_RC"):
        sys.exit(int(os.environ["FAKE_TMUX_POPUP_RC"]))   # what the popup's command exited with
'''

FAKE_LOGGER = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.path.join(os.environ["HOME"], os.path.basename(sys.argv[0]) + ".log"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
'''

# xdg-mime stand-in: remembers one default per scheme in $HOME/.fake-mime
FAKE_XDG_MIME = r'''#!/usr/bin/env python3
import json, os, sys
home = os.environ["HOME"]
with open(os.path.join(home, "xdg-mime.log"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
store = os.path.join(home, ".fake-mime")
if sys.argv[1:3] == ["query", "default"]:
    if os.path.exists(store):
        sys.stdout.write(open(store).read() + "\n")
elif sys.argv[1:2] == ["default"]:
    open(store, "w").write(sys.argv[2])
'''


class ShellHarness(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="rh")
        self.home = os.path.join(self.tmp, "h")
        self.bin = os.path.join(self.home, ".local", "bin")
        os.makedirs(self.bin)
        for name, src in (("tmux", FAKE_TMUX), ("xdg-open", FAKE_LOGGER),
                          ("update-desktop-database", FAKE_LOGGER),
                          ("xdg-mime", FAKE_XDG_MIME)):
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write(src)
            os.chmod(path, 0o755)
        self.work = os.path.join(self.tmp, "work dir")
        os.makedirs(self.work)
        if shutil.which("git"):  # the diff action only runs inside a repository
            subprocess.run(["git", "init", "-q", self.work], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)

    def tearDown(self):
        import shutil as sh
        sh.rmtree(self.tmp, ignore_errors=True)

    def env(self, extra=None):
        # built from scratch: no XDG_* dirs or TMUX from the developer's shell
        env = {"HOME": self.home, "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        env.update(extra or {})
        return env

    def run_handler(self, *args, **extra):
        extra.setdefault("FAKE_TMUX_PANE_PATH", self.work)
        return subprocess.run(["bash", HANDLER] + list(args), env=self.env(extra),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=20)

    def log(self, name):
        import json
        path = os.path.join(self.home, name + ".log")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(line) for line in f]

    def tmux_calls(self, verb=None):
        calls = [c[2:] if c[:1] == ["-S"] else c for c in self.log("tmux")]
        return [c for c in calls if verb is None or c[:1] == [verb]]

    def handler_log(self):
        path = os.path.join(self.home, ".cache", "retro-hud", "handler.log")
        if not os.path.exists(path):
            return ""
        with open(path) as f:
            return f.read()

    def write_config(self, text):
        d = os.path.join(self.home, ".config", "retro-hud")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "env"), "w") as f:
            f.write(text)

    def url(self, action, **q):
        from urllib.parse import quote
        q.setdefault("pane", "%7")
        return "retro-hud://{}?{}".format(action, "&".join(
            "{}={}".format(k, quote(v, safe="/")) for k, v in q.items()))

    def menu(self):
        """The one display-menu call: (client, title, [(label, key, command)])."""
        menus = self.tmux_calls("display-menu")
        self.assertEqual(len(menus), 1, self.log("tmux"))
        argv = menus[0]
        i = 1
        opts = {}
        while argv[i].startswith("-"):
            if argv[i] == "-O":      # bare flag: keep the menu open across a mouse release
                opts["-O"] = True
                i += 1
                continue
            opts[argv[i]] = argv[i + 1]
            i += 2
        self.assertTrue(opts.get("-O"), "menus must keep open across the right-click release")
        rest = argv[i:]
        items = [tuple(rest[j:j + 3]) for j in range(0, len(rest), 3)]
        return opts.get("-c"), opts.get("-T"), items


class TestHandlerRejects(ShellHarness):
    def assert_rejected(self, *args, **extra):
        p = self.run_handler(*args, **extra)
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(self.tmux_calls(), [], args)
        self.assertEqual(self.log("xdg-open"), [], args)
        self.assertIn("reject", self.handler_log(), args)

    def test_argument_count(self):
        self.assert_rejected()
        self.assert_rejected(self.url("cost"), "extra")

    def test_whitelist(self):
        for bad in ("retro-hud://rm", "retro-hud://cost;id", "http://example.com",
                    "retro-hud://cost?pane=%257;touch x", "retro-hud://cost?pane=$(id)",
                    "retro-hud://costs?pane=%257", "retro-hud://cost/x",
                    "retro-hud://cost?pane=%257\n", "RETRO-HUD://cost",
                    "retro-hud://agents?pane=%257", "retro-hud://agent?pane=x",
                    "retro-hud://agent?pane=%257;id", "retro-hud://agent/wave?pane=%257"):
            self.assert_rejected(bad)

    def test_crafted_pane(self):
        for pane in ("%7;touch x", "7", "%", "%7 ", "%%7", "%7\n%8"):
            self.assert_rejected(self.url("cost", pane=pane))
        self.assert_rejected("retro-hud://cost")   # pane required
        self.assert_rejected("retro-hud://diff")

    def test_crafted_sock(self):
        self.assert_rejected(self.url("cost", sock=self.work))        # a dir
        self.assert_rejected(self.url("cost", sock="/no/such/sock"))

    def test_crafted_effort_level(self):
        self.assert_rejected(self.url("effort", cur="turbo"))

    def test_nothing_runs_from_the_url(self):
        marker = os.path.join(self.tmp, "pwned")
        self.run_handler(self.url("cost", pane="%7$(touch {})".format(marker)))
        self.run_handler(self.url("diff", cwd="$(touch {})".format(marker)))
        self.assertFalse(os.path.exists(marker))

    def test_unknown_query_keys_are_ignored(self):
        p = self.run_handler(self.url("cost", sid="abc", extra="1"))
        self.assertEqual(p.returncode, 0)
        self.assertEqual(len(self.tmux_calls("send-keys")), 2)


class TestHandlerActions(ShellHarness):
    def test_cost_types_slash_cost(self):
        p = self.run_handler(self.url("cost"))
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(self.tmux_calls("send-keys"),
                         [["send-keys", "-t", "%7", "-l", "/cost"],
                          ["send-keys", "-t", "%7", "Enter"]])
        self.assertEqual(p.stdout, b"")

    def test_send_refused_when_pane_is_not_claude(self):
        self.run_handler(self.url("cost"), FAKE_TMUX_PANE_CMD="bash")
        self.assertEqual(self.tmux_calls("send-keys"), [])
        msgs = self.tmux_calls("display-message")
        self.assertTrue(any("no longer running Claude" in " ".join(m) for m in msgs), msgs)

    def test_send_allowed_when_claude_is_the_panes_child(self):
        # a launcher script in front: pane_current_command is bash, claude its child
        fake = os.path.join(self.tmp, "claude")
        shutil.copy("/bin/sleep", fake)
        os.chmod(fake, 0o755)
        wrapper = subprocess.Popen(["bash", "-c", '"$0" 30; true', fake])
        self.addCleanup(wrapper.kill)
        for _ in range(50):
            if subprocess.run(["pgrep", "-P", str(wrapper.pid), "-x", "claude"],
                              stdout=subprocess.PIPE).stdout:
                break
            time.sleep(0.05)
        self.run_handler(self.url("cost"), FAKE_TMUX_PANE_CMD="bash",
                         FAKE_TMUX_PANE_PID=str(wrapper.pid))
        self.assertTrue(self.tmux_calls("send-keys"))
        self.run_handler(self.url("cost"), FAKE_TMUX_PANE_CMD="bash", FAKE_TMUX_PANE_PID="1")
        self.assertEqual(len(self.tmux_calls("send-keys")), 2)  # unchanged: refused

    def test_diff_outside_a_repository_says_so(self):
        self.run_handler(self.url("diff"), FAKE_TMUX_PANE_PATH=self.tmp)
        self.assertEqual(self.tmux_calls("display-popup"), [])
        msgs = self.tmux_calls("display-message")
        self.assertTrue(any("no git repository" in " ".join(m) and "-d" in m for m in msgs), msgs)

    def test_diff_dir_override_from_a_local_extension(self):
        # RETRO_HUD_DIFF_DIR (an absolute existing directory) wins over the pane's path
        argv = self.diff_popup(self.url("diff"), FAKE_TMUX_PANE_PATH=self.tmp, RETRO_HUD_DIFF_DIR=self.work)
        self.assertEqual(argv[argv.index("-d") + 1], self.work)
        for bad in ("relative", "/no/such/dir", self.work + "\n/tmp"):
            self.run_handler(self.url("diff"), FAKE_TMUX_PANE_PATH=self.tmp, RETRO_HUD_DIFF_DIR=bad)
        self.assertEqual(len(self.tmux_calls("display-popup")), 1)

    def test_send_verifies_the_clicked_pane(self):
        self.run_handler(self.url("cost", pane="%42"), FAKE_TMUX_ACTIVE_PANE="%42")
        probe = [c for c in self.tmux_calls("display") if "-t" in c]
        self.assertEqual(probe, [["display", "-p", "-t", "%42", "#{pane_current_command}"]])
        active = [c for c in self.tmux_calls("display") if "-c" in c]
        self.assertEqual(active, [["display", "-p", "-c", "/dev/pts/3", "#{pane_id}"]])

    def test_link_for_another_pane_does_nothing(self):
        # A link printed by something else could name a different Claude
        # pane; only the clicking client's active pane is ever a target.
        for action in ("cost", "model", "effort", "ctx", "diff"):
            p = self.run_handler(self.url(action, pane="%8"))
            self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(self.tmux_calls("send-keys"), [])
        self.assertEqual(self.tmux_calls("display-menu"), [])
        self.assertEqual(self.tmux_calls("display-popup"), [])
        msgs = [" ".join(m) for m in self.tmux_calls("display-message")]
        self.assertEqual(len(msgs), 5, msgs)
        self.assertTrue(all("link targets a different pane" in m for m in msgs), msgs)

    def test_do_send_checks_the_active_pane_too(self):
        self.run_handler("do", "send", "%3", "cost")   # active pane is %7
        self.assertEqual(self.tmux_calls("send-keys"), [])

    def test_do_send(self):
        p = self.run_handler("do", "send", "%3", "effort", "xhigh",
                             FAKE_TMUX_ACTIVE_PANE="%3")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(self.tmux_calls("send-keys"),
                         [["send-keys", "-t", "%3", "-l", "/effort xhigh"],
                          ["send-keys", "-t", "%3", "Enter"]])

    def test_do_send_rejects_free_text(self):
        for args in (("send", "%3", "effort", "turbo"), ("send", "%3", "model", "a b"),
                     ("send", "%3", "model", "x;id"), ("send", "%3", "rm"),
                     ("send", "3", "cost"), ("send", "%3", "cost", "extra"),
                     ("exec", "%3", "cost")):
            self.run_handler("do", *args)
            self.assertEqual(self.tmux_calls("send-keys"), [], args)

    def test_model_menu_defaults(self):
        self.run_handler(self.url("model"))
        client, title, items = self.menu()
        self.assertEqual(client, "/dev/pts/3")  # newest client_activity
        self.assertTrue(title.endswith("(types into the composer)"), title)
        labels = [i[0] for i in items]
        self.assertEqual(labels[:3], ["opus", "sonnet", "haiku"])
        self.assertTrue(labels[-1].startswith("pick"))
        self.assertIn("do send '%7' model opus", items[0][2])
        self.assertIn("do send '%7' model", items[-1][2])
        self.assertNotIn("pick", items[-1][2])

    def test_model_menu_from_config_file(self):
        marker = os.path.join(self.tmp, "pwned")
        self.write_config(
            "# comment\n\nRETRO_HUD_MODELS=fable, opus[1m] ,bad;item\n"
            "PATH=/evil\nexport RETRO_HUD_USAGE_URL=x\n"
            "RETRO_HUD_EVIL=$(touch {})\n$(touch {})\n".format(marker, marker))
        self.run_handler(self.url("model"))
        labels = [i[0] for i in self.menu()[2]]
        self.assertEqual(labels[:2], ["fable", "opus[1m]"])
        self.assertEqual(len(labels), 3)
        self.assertFalse(os.path.exists(marker))

    def test_environment_overrides_config_file(self):
        self.write_config("RETRO_HUD_MODELS=fable\n")
        self.run_handler(self.url("model"), RETRO_HUD_MODELS="sonnet")
        self.assertEqual(self.menu()[2][0][0], "sonnet")

    def test_effort_menu_marks_current(self):
        self.run_handler(self.url("effort", cur="high"))
        _, title, items = self.menu()
        self.assertIn("(types into the composer)", title)
        self.assertEqual([i[0].split()[0] for i in items],
                         ["low", "medium", "high", "xhigh", "max"])
        self.assertIn("current", items[2][0])
        self.assertEqual(sum("current" in i[0] for i in items), 1)
        self.assertTrue(items[4][2].endswith("do send '%7' effort max\""), items[4][2])

    def test_ctx_menu_and_clear_confirm(self):
        self.run_handler(self.url("ctx"))
        _, _, items = self.menu()
        cmds = " ".join(i[2] for i in items)
        self.assertIn("send '%7' compact", cmds)
        self.assertIn("send '%7' context", cmds)
        self.assertNotIn("send '%7' clear", cmds)      # behind the confirm menu
        self.assertIn("confirm-clear '%7'", cmds)
        os.remove(os.path.join(self.home, "tmux.log"))
        self.run_handler("do", "confirm-clear", "%7")
        _, title, items = self.menu()
        self.assertIn("clear", title)
        self.assertIn("send '%7' clear", " ".join(i[2] for i in items))
        self.assertEqual(self.tmux_calls("send-keys"), [])

    def test_menu_commands_reenter_handler_with_safe_tokens(self):
        for action in ("model", "effort", "ctx"):
            self.run_handler(self.url(action, cur="max"))
        for argv in self.tmux_calls("display-menu"):
            for cmd in argv[argv.index("-T") + 2:][2::3]:
                if cmd:
                    self.assertRegex(
                        cmd, r"^run-shell -b \"'" + re.escape(HANDLER) +
                        r"' do (-S '[^']*' )?(send|confirm-clear) '%7'( [A-Za-z0-9._:\[\]-]+)*\"$")

    def diff_popup(self, *args, **extra):
        self.run_handler(*args, **extra)
        popups = self.tmux_calls("display-popup")
        self.assertEqual(len(popups), 1, self.log("tmux"))
        return popups[0]

    def test_diff_popup_runs_in_the_panes_own_directory(self):
        # a cwd in the URL is ignored: the directory comes from tmux
        argv = self.diff_popup(self.url("diff", cwd="/tmp"))
        self.assertEqual(argv[argv.index("-d") + 1], self.work)
        self.assertEqual(argv[argv.index("-c") + 1], "/dev/pts/3")
        self.assertIn("-E", argv)
        self.assertNotIn(self.work, argv[-1])  # the path never reaches a shell string
        self.assertIn(["display", "-p", "-t", "%7", "#{pane_current_path}"],
                      self.tmux_calls("display"))
        self.assertEqual(self.tmux_calls("send-keys"), [])

    def test_diff_needs_a_real_pane_directory(self):
        for path in ("", "relative", "/no/such/dir", self.work + "\n/tmp"):
            self.run_handler(self.url("diff"), FAKE_TMUX_PANE_PATH=path)
        self.assertEqual(self.tmux_calls("display-popup"), [])

    def test_diff_git_is_hardened(self):
        cmd = self.diff_popup(self.url("diff"))[-1]
        for flag in ("GIT_CONFIG_NOSYSTEM=1", "GIT_OPTIONAL_LOCKS=0",
                     "-c core.fsmonitor=false", "-c diff.external=", "-c core.pager=",
                     "--no-pager", "--no-ext-diff", "--no-textconv", "LESSSECURE=1",
                     "--mouse", "working tree clean", "show --stat --patch"):
            self.assertIn(flag, cmd)
        self.assertNotIn("LESSKEYIN", cmd)   # an Esc binding would quit on every wheel report

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_diff_popup_command_ignores_a_hostile_repo_config(self):
        # Run the popup's exact command in a repo whose config tries to
        # execute a program via fsmonitor, an external diff and textconv.
        cmd = self.diff_popup(self.url("diff"))[-1]
        marker = os.path.join(self.tmp, "pwned")
        evil = os.path.join(self.tmp, "evil.sh")
        with open(evil, "w") as f:
            f.write("#!/bin/sh\ntouch '{}'\n".format(marker))
        os.chmod(evil, 0o755)
        genv = self.env({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
                         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"})

        def git(*a):
            subprocess.run(["git"] + list(a), cwd=self.work, env=genv, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        git("init", "-q")
        with open(os.path.join(self.work, "f.txt"), "w") as f:
            f.write("one\n")
        with open(os.path.join(self.work, ".gitattributes"), "w") as f:
            f.write("*.txt diff=evil\n")
        git("add", ".")
        git("commit", "-qm", "x")
        for key in ("core.fsmonitor", "diff.external", "diff.evil.textconv",
                    "diff.evil.command", "core.pager"):
            git("config", key, evil)
        with open(os.path.join(self.work, "f.txt"), "w") as f:
            f.write("two\n")
        p = subprocess.run(["sh", "-c", cmd], cwd=self.work, env=genv,
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=20)
        out = sl.strip_ansi(p.stdout.decode())
        self.assertFalse(os.path.exists(marker), out)
        self.assertIn("+two", out)
        # the same repo does run the hostile program for a plain git diff,
        # so the assertion above is meaningful
        subprocess.run(["git", "diff"], cwd=self.work, env=genv, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        self.assertTrue(os.path.exists(marker))

    def test_usage_opens_browser(self):
        self.run_handler("retro-hud://usage")
        self.assertEqual(self.log("xdg-open"), [["https://claude.ai/settings/usage"]])
        self.write_config("RETRO_HUD_USAGE_URL=https://example.com/usage?a=1\n")
        self.run_handler(self.url("usage"))
        self.assertEqual(self.log("xdg-open")[-1], ["https://example.com/usage?a=1"])
        self.assertEqual(self.tmux_calls("send-keys"), [])

    def test_usage_rejects_non_web_url_from_config(self):
        self.write_config("RETRO_HUD_USAGE_URL=file:///etc/passwd\n")
        self.run_handler("retro-hud://usage")
        self.assertEqual(self.log("xdg-open"), [["https://claude.ai/settings/usage"]])

    def test_sock_addresses_that_server(self):
        import socket
        path = os.path.join(self.tmp, "s")
        s = socket.socket(socket.AF_UNIX)
        s.bind(path)
        try:
            self.run_handler(self.url("model", sock=path))
            raw = self.log("tmux")
            self.assertTrue(raw)
            for argv in raw:
                self.assertEqual(argv[:2], ["-S", path])
            self.assertIn("do -S '{}' send '%7' model".format(path),
                          " ".join(self.menu()[2][0]))
        finally:
            s.close()

    def test_unsafe_install_path_shows_no_menu(self):
        # Menu items embed the handler's own path in a tmux command; a path
        # with quotes or $ could break out of it, so no menu is shown.
        odd = os.path.join(self.tmp, "it's $x")
        os.makedirs(odd)
        copy_path = os.path.join(odd, "retro-hud-handler.sh")
        shutil.copy(HANDLER, copy_path)
        p = subprocess.run(["bash", copy_path, self.url("model")],
                           env=self.env({"FAKE_TMUX_PANE_PATH": self.work}),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(self.tmux_calls("display-menu"), [])
        self.assertIn("unsafe", self.handler_log())

    def test_no_tmux_server_is_logged_not_fatal(self):
        p = self.run_handler(self.url("model"), FAKE_TMUX_NOSERVER="1")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertIn("client", self.handler_log())

    def test_local_extension_runs_first(self):
        d = os.path.join(self.home, ".claude")
        os.makedirs(d)
        with open(os.path.join(d, "retro-hud-handler.local.sh"), "w") as f:
            f.write('[ "$1" = "retro-hud://cost?pane=%257" ] && '
                    '{ echo "$1" > "$HOME/local.out"; exit 0; }\n')
        self.run_handler("retro-hud://cost?pane=%257")
        self.assertTrue(os.path.exists(os.path.join(self.home, "local.out")))
        self.assertEqual(self.tmux_calls(), [])
        self.run_handler(self.url("ctx"))       # not handled locally: built-in runs
        self.assertEqual(len(self.tmux_calls("display-menu")), 1)


class TestHandlerInBinding(ShellHarness):
    """Inside a tmux right-click binding: RETRO_HUD_MENU_FILE and RETRO_HUD_CLIENT.
    A display-menu run by the handler itself has no mouse event, so tmux 3.4 makes it a
    keyboard menu that the right button's own release closes. The binding therefore runs
    the handler synchronously, the handler writes the menu as one line, and the binding
    source-files it with the press's event (fixed 2026-10-23)."""

    def setUp(self):
        super().setUp()
        self.menu_file = os.path.join(self.tmp, "menu-_dev_pts_3.tmux")

    def bound(self, *args, **extra):
        extra.setdefault("RETRO_HUD_MENU_FILE", self.menu_file)
        extra.setdefault("RETRO_HUD_CLIENT", "/dev/pts/3")
        return self.run_handler(*args, **extra)

    def test_menu_is_written_for_the_binding_not_shown(self):
        p = self.bound(self.url("ctx"))
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(self.tmux_calls("display-menu"), [], "the binding runs it, not the handler")
        with open(self.menu_file) as f:
            line = f.read()
        self.assertEqual(line.count("\n"), 1)
        self.assertTrue(line.startswith(
            "display-menu -O -c '/dev/pts/3' -T 'context (types into the composer)' -x M -y '#{popup_mouse_y}' -- "), line)
        self.assertIn(" '/compact' 'c' 'run-shell -b \"'\\''", line)   # items quoted, quotes inside escaped
        self.assertIn("confirm-clear '\\''%7'\\''", line)

    def test_bound_client_is_the_menus_client(self):
        self.bound(self.url("effort", cur="high"), RETRO_HUD_CLIENT="/dev/pts/9")
        self.assertEqual(self.tmux_calls("list-clients"), [], "the binding named the client")
        with open(self.menu_file) as f:
            self.assertIn("display-menu -O -c '/dev/pts/9' ", f.read())
        active = [c for c in self.tmux_calls("display") if "-c" in c]
        self.assertEqual(active, [["display", "-p", "-c", "/dev/pts/9", "#{pane_id}"]])

    def test_a_non_menu_action_removes_a_stale_file(self):
        with open(self.menu_file, "w") as f:
            f.write("display-menu stale\n")
        self.bound(self.url("cost"))
        self.assertFalse(os.path.exists(self.menu_file), "nothing left for source-file to run")
        self.assertEqual(self.tmux_calls("send-keys")[0], ["send-keys", "-t", "%7", "-l", "/cost"])

    def test_malformed_variables_are_ignored(self):
        self.bound(self.url("ctx"), RETRO_HUD_MENU_FILE=os.path.join(self.tmp, "m;rm.tmux"), RETRO_HUD_CLIENT="pts3")
        client, title, items = self.menu()      # shown directly, on the newest client
        self.assertEqual(client, "/dev/pts/3")
        self.assertIn("RETRO_HUD_MENU_FILE ignored", self.handler_log())
        self.assertIn("RETRO_HUD_CLIENT ignored", self.handler_log())

    def test_diff_is_detached_so_the_binding_never_waits(self):
        import time
        t0 = time.time()
        p = self.bound(self.url("diff"))
        self.assertLess(time.time() - t0, 5)
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        for _ in range(50):            # the detached copy runs the popup
            if self.tmux_calls("display-popup"):
                break
            time.sleep(0.1)
        self.assertEqual(len(self.tmux_calls("display-popup")), 1, self.log("tmux"))

    @unittest.skipUnless(shutil.which("tmux"), "needs a real tmux")
    def test_menu_line_parses_in_a_real_tmux(self):
        # the whole line through tmux's own parser: every token comes back verbatim
        self.bound(self.url("ctx"))
        with open(self.menu_file) as f:
            line = f.read().strip()
        import shlex
        tokens = shlex.split(line)     # the quoting is shell-compatible by construction
        quoted = quoted_tokens(line)
        self.assertEqual(len(quoted), len(tokens))
        probe = os.path.join(self.tmp, "probe.tmux")
        with open(probe, "w") as f:
            f.write("\n".join("set -g @t%d %s" % (i, q) for i, q in enumerate(quoted)) + "\n")
        sock = os.path.join(self.tmp, "sock")
        subprocess.run(["tmux", "-S", sock, "-f", "/dev/null", "new-session", "-d", ";", "source-file", probe],
                       capture_output=True, timeout=20)
        got = [subprocess.run(["tmux", "-S", sock, "display", "-p", "#{@t%d}" % i],
                              capture_output=True, text=True, timeout=20).stdout[:-1] for i in range(len(tokens))]
        subprocess.run(["tmux", "-S", sock, "kill-server"], capture_output=True)
        self.assertEqual(got, tokens)


def quoted_tokens(line):
    """Split a tmux command line into its quoted tokens, keeping each token's quoting."""
    out, cur, q = [], "", False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "'" and line[i:i + 4] != "'\\''":
            q = not q
            cur += ch
        elif ch == "'" and line[i:i + 4] == "'\\''":
            cur += "'\\''"
            i += 3
        elif ch == " " and not q:
            out.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    if cur:
        out.append(cur)
    return out


class TestHandlerAgent(ShellHarness):
    """The `agent` action: a menu that talks to the HUD through its cache
    files, found via the pane → session map the HUD writes."""
    SID = "0d7e5c1a-session"

    def setUp(self):
        super().setUp()
        self.cache = os.path.join(self.home, ".cache", "retro-hud")

    def map_pane(self, pane="7", sid=None, cache=None):
        cache = cache or self.cache
        os.makedirs(cache, exist_ok=True)
        with open(os.path.join(cache, "pane-{}.sid".format(pane)), "w") as f:
            f.write(self.SID if sid is None else sid)

    def state_path(self, cache=None):
        return os.path.join(cache or self.cache, self.SID + ".state.json")

    def put_state(self, obj, cache=None):
        os.makedirs(cache or self.cache, exist_ok=True)
        with open(self.state_path(cache), "w") as f:
            json.dump(obj, f)

    def get_state(self, cache=None):
        with open(self.state_path(cache)) as f:
            return json.load(f)

    def messages(self):
        return [m[-1] for m in self.tmux_calls("display-message")]

    def test_url_shows_the_agent_menu(self):
        self.map_pane()
        p = self.run_handler(self.url("agent"))
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        client, title, items = self.menu()
        self.assertEqual(client, "/dev/pts/3")
        self.assertIn("agent", title)
        self.assertEqual([i[0] for i in items], ["status card", "wave", "quiet 1h", "sprite ▸", "status"])
        self.assertEqual(items[0][1:], ("c", "run-shell -b \"'{}' 'retro-hud://card?pane=%257'\"".format(HANDLER)))
        prefix = "run-shell -b \"'{}' do agent '%7' ".format(HANDLER)
        self.assertEqual([i[2] for i in items[1:]],
                         [prefix + sub + '"' for sub in ("wave", "quiet", "sprites", "status")])
        self.assertEqual(items[2][1], "h", "quiet is not on q: q closes a tmux menu")

    def test_menu_title_names_the_agent_from_config(self):
        self.map_pane()
        self.write_config("RETRO_HUD_AGENT_NAME=Nova\n")
        self.run_handler(self.url("agent"))
        self.assertIn("Nova", self.menu()[1])

    def test_hostile_agent_name_is_ignored(self):
        self.map_pane()
        self.run_handler(self.url("agent"), RETRO_HUD_AGENT_NAME="#(id)x")
        title = self.menu()[1]
        self.assertNotIn("#", title)
        self.assertIn("agent", title)

    def test_agent_url_needs_a_pane(self):
        self.map_pane()
        p = self.run_handler("retro-hud://agent")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(self.tmux_calls(), [])
        self.assertIn("reject", self.handler_log())

    def test_agent_only_for_the_active_claude_pane(self):
        self.map_pane("8")
        self.run_handler(self.url("agent", pane="%8"))       # active pane is %7
        self.map_pane()
        self.run_handler(self.url("agent"), FAKE_TMUX_PANE_CMD="bash")
        self.assertEqual(self.tmux_calls("display-menu"), [])
        msgs = self.messages()
        self.assertTrue(any("different pane" in m for m in msgs), msgs)
        self.assertTrue(any("no longer running Claude" in m for m in msgs), msgs)

    def test_no_session_map_means_no_menu(self):
        self.run_handler(self.url("agent"))
        self.assertEqual(self.tmux_calls("display-menu"), [])
        self.assertTrue(any("no agent" in m for m in self.messages()), self.messages())

    def test_hostile_session_map_is_refused(self):
        for sid in ("../../etc/x", "a b", "", "x" * 200):
            self.map_pane(sid=sid)
            self.run_handler("do", "agent", "%7", "quiet")
        self.assertEqual([n for n in os.listdir(self.cache) if not n.startswith(("pane-", "handler"))], [])

    def test_do_wave_appends_a_10s_wave_event(self):
        self.map_pane()
        before = int(time.time())
        p = self.run_handler("do", "agent", "%7", "wave")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        with open(os.path.join(self.cache, self.SID + ".events.jsonl")) as f:
            lines = [json.loads(ln) for ln in f]
        self.assertEqual(len(lines), 1)
        ev = lines[0]
        self.assertEqual((ev["text"], ev["ttl"]), ("wave", 10))
        self.assertTrue(before <= ev["ts"] <= time.time() + 1, ev)
        self.assertEqual(ev["text"], sl.WAVE_EVENT)  # what the HUD waves at

    def test_do_quiet_sets_mute_until_and_keeps_every_other_key(self):
        self.map_pane()
        fixture = {"state": "working", "since": 123, "ctx_pct": 42, "limit_pct": 63,
                   "cost": 3.21, "bubble": {"text": "ready", "until": 9}, "sprite": "cat",
                   "custom": [1, 2]}
        self.put_state(fixture)
        before = int(time.time())
        self.run_handler("do", "agent", "%7", "quiet")
        got = self.get_state()
        mute = got.pop("mute_until")
        self.assertTrue(before + 3600 <= mute <= time.time() + 3601, mute)
        self.assertEqual(got, fixture)
        self.assertEqual([n for n in os.listdir(self.cache) if n.endswith(".tmp")], [])

    def test_do_quiet_creates_a_missing_state_file(self):
        self.map_pane()
        self.run_handler("do", "agent", "%7", "quiet")
        self.assertEqual(set(self.get_state()), {"mute_until"})

    def test_corrupt_state_file_is_left_alone(self):
        self.map_pane()
        os.makedirs(self.cache, exist_ok=True)
        with open(self.state_path(), "w") as f:
            f.write("{not json")
        self.run_handler("do", "agent", "%7", "sprite", "cat")
        with open(self.state_path()) as f:
            self.assertEqual(f.read(), "{not json")

    def test_do_sprite_writes_and_default_removes(self):
        self.map_pane()
        self.put_state({"state": "yours", "since": 5})
        for name in ("alien", "cat", "robot", "ghost"):
            self.run_handler("do", "agent", "%7", "sprite", name)
            self.assertEqual(self.get_state(), {"state": "yours", "since": 5, "sprite": name})
        self.run_handler("do", "agent", "%7", "sprite", "default")
        self.assertEqual(self.get_state(), {"state": "yours", "since": 5})

    def test_do_sprite_rejects_unknown_names(self):
        self.map_pane()
        self.put_state({"state": "yours"})
        for args in (("sprite", "dragon"), ("sprite",), ("sprite", "cat", "x"),
                     ("sprite", "cat;id"), ("rm",), ("quiet", "now")):
            self.run_handler("do", "agent", "%7", *args)
            self.assertEqual(self.get_state(), {"state": "yours"}, args)
        self.assertIn("reject", self.handler_log())

    def test_sprite_submenu(self):
        self.map_pane()
        self.run_handler("do", "agent", "%7", "sprites")
        _, title, items = self.menu()
        self.assertIn("sprite", title)
        self.assertEqual([i[0] for i in items], ["alien", "cat", "robot", "ghost", "default"])
        prefix = "run-shell -b \"'{}' do agent '%7' sprite ".format(HANDLER)
        self.assertEqual([i[2] for i in items],
                         [prefix + n + '"' for n in ("alien", "cat", "robot", "ghost", "default")])

    def test_creature_menu_offers_reroll(self):
        self.map_pane()
        self.put_state({"state": "yours", "creature": "alien"})
        self.run_handler(self.url("agent"))
        _, _, items = self.menu()
        self.assertEqual([i[0] for i in items],
                         ["status card", "wave", "quiet 1h", "sprite ▸", "size ▸", "reroll", "status"])
        self.assertEqual((items[4][1], items[5][1]), ("z", "r"))
        prefix = "run-shell -b \"'{}' do agent '%7' ".format(HANDLER)
        self.assertEqual(items[4][2], prefix + 'sizes"')
        self.assertEqual(items[5][2], prefix + 'reroll"')

    def test_creature_sprite_submenu_lists_families(self):
        self.map_pane()
        self.put_state({"creature": "bot"})
        self.run_handler("do", "agent", "%7", "sprites")
        _, _, items = self.menu()
        self.assertEqual([i[0] for i in items], ["blob", "beast", "alien", "bot", "robot", "default"])

    def test_reroll_writes_a_seed_and_says_how_to_pin_it(self):
        self.map_pane()
        self.put_state({"creature": "alien", "mute_until": 5})
        self.run_handler("do", "agent", "%7", "reroll")
        st = self.get_state()
        self.assertEqual(st["mute_until"], 5)
        self.assertIsInstance(st["seed"], int)
        self.assertTrue(0 <= st["seed"] < 2 ** 32)
        msg = self.messages()[-1]
        self.assertIn("RETRO_HUD_CREATURE_SEED={}".format(st["seed"]), msg)
        first = st["seed"]
        self.run_handler("do", "agent", "%7", "reroll")
        self.assertNotEqual(self.get_state()["seed"], first)

    def test_size_submenu(self):
        self.map_pane()
        self.put_state({"creature": "alien"})
        self.run_handler("do", "agent", "%7", "sizes")
        _, title, items = self.menu()
        self.assertIn("size", title)
        names = ["tiny", "big", "tall", "default"]
        self.assertEqual([i[0] for i in items], names)
        prefix = "run-shell -b \"'{}' do agent '%7' size ".format(HANDLER)
        self.assertEqual([i[2] for i in items], [prefix + n + '"' for n in names])

    def test_do_size_writes_and_default_removes(self):
        self.map_pane()
        self.put_state({"creature": "alien", "seed": 3})
        for name in ("big", "tall", "tiny"):
            self.run_handler("do", "agent", "%7", "size", name)
            self.assertEqual(self.get_state(), {"creature": "alien", "seed": 3, "size": name})
        self.run_handler("do", "agent", "%7", "size", "default")
        self.assertEqual(self.get_state(), {"creature": "alien", "seed": 3})

    def test_do_size_rejects_unknown_sizes(self):
        self.map_pane()
        self.put_state({"creature": "alien"})
        for args in (("size", "huge"), ("size",), ("size", "big", "x"), ("size", "big;id"),
                     ("sizes", "x")):
            self.run_handler("do", "agent", "%7", *args)
            self.assertEqual(self.get_state(), {"creature": "alien"}, args)
        self.assertIn("reject", self.handler_log())

    def test_size_reaches_the_hud(self):
        # the state file's size, written by the menu, is what the HUD draws
        self.map_pane()
        self.put_state({"creature": "alien"})
        self.run_handler("do", "agent", "%7", "size", "tall")
        saved = os.environ.get("RETRO_HUD_CACHE_DIR")
        os.environ["RETRO_HUD_CACHE_DIR"] = self.cache
        os.environ["RETRO_HUD_CREATURE"] = "tiny"
        try:
            self.assertEqual(sl.creature_size({"session_id": self.SID}), "tall")
        finally:
            os.environ["RETRO_HUD_CACHE_DIR"] = saved
            os.environ["RETRO_HUD_CREATURE"] = "0"

    def test_family_sprites_are_accepted(self):
        self.map_pane()
        self.put_state({"creature": "alien"})
        for fam in ("blob", "beast", "bot", "alien"):
            self.run_handler("do", "agent", "%7", "sprite", fam)
            self.assertEqual(self.get_state()["sprite"], fam)
        self.run_handler("do", "agent", "%7", "reroll", "x")
        self.assertNotIn("seed", self.get_state())

    def test_do_status_composes_the_snapshot(self):
        self.map_pane()
        self.put_state({"state": "working", "since": int(time.time()) - 185,
                        "ctx_pct": 42, "limit_pct": 63, "cost": 3.21})
        self.run_handler("do", "agent", "%7", "status")
        msg, = self.messages()
        self.assertRegex(msg, r"working for 3m")
        for part in ("ctx 42%", "limit 63%", "$3.21"):
            self.assertIn(part, msg)
        self.assertNotIn("#", msg)
        self.assertEqual(self.tmux_calls("display-message")[0][:3],
                         ["display-message", "-c", "/dev/pts/3"])

    def test_do_status_without_snapshot(self):
        self.map_pane()
        self.run_handler("do", "agent", "%7", "status")
        msg, = self.messages()
        self.assertIn("no status", msg)

    def test_do_status_ignores_hostile_values(self):
        self.map_pane()
        self.put_state({"state": "#(id)", "since": "x", "ctx_pct": "#{pane}",
                        "limit_pct": None, "cost": [1]})
        self.run_handler("do", "agent", "%7", "status")
        msg, = self.messages()
        self.assertNotIn("#", msg)
        self.assertNotIn("id", msg)

    def test_do_agent_checks_the_active_claude_pane(self):
        self.map_pane("3")
        self.put_state({"state": "yours"})
        self.run_handler("do", "agent", "%3", "quiet")                  # active is %7
        self.run_handler("do", "agent", "%3", "sprite", "cat",
                         FAKE_TMUX_ACTIVE_PANE="%3", FAKE_TMUX_PANE_CMD="zsh")
        self.assertEqual(self.get_state(), {"state": "yours"})

    def test_cache_dir_from_environment_and_config(self):
        other = os.path.join(self.tmp, "elsewhere")
        self.map_pane(cache=other)
        self.put_state({"state": "yours"}, cache=other)
        self.run_handler("do", "agent", "%7", "sprite", "cat", RETRO_HUD_CACHE_DIR=other)
        self.assertEqual(self.get_state(other)["sprite"], "cat")
        self.write_config("RETRO_HUD_CACHE_DIR={}\n".format(other))
        self.run_handler("do", "agent", "%7", "sprite", "ghost")
        self.assertEqual(self.get_state(other)["sprite"], "ghost")
        self.assertFalse(os.path.exists(self.state_path()))

    def test_relative_cache_dir_is_refused(self):
        self.map_pane()
        self.put_state({"state": "yours"})
        self.run_handler("do", "agent", "%7", "sprite", "cat", RETRO_HUD_CACHE_DIR="rel/dir")
        self.assertEqual(self.get_state(), {"state": "yours"})


class TestHandlerCard(TestHandlerAgent):
    """The `card` action: the creature's status card, a popup from the
    state file's facts plus one tip; any key closes it, m opens the menu."""

    def popup(self):
        pops = self.tmux_calls("display-popup")
        self.assertEqual(len(pops), 1, self.log("tmux"))
        argv = pops[0]
        opts = {argv[i]: argv[i + 1] for i in range(1, len(argv) - 1, 2)}
        self.assertEqual(opts["-c"], "/dev/pts/3")
        self.assertRegex(opts["-E"], r"^bash '[^']+'$")
        with open(os.path.join(self.home, "popup.runner")) as f:
            runner = f.read()
        with open(os.path.join(self.home, "popup.card")) as f:
            text = f.read()
        self.assertEqual([n for n in os.listdir(os.path.join(self.home, ".cache", "retro-hud")) if n.startswith("card.")],
                         [], "the card's files are removed once the popup returns")
        return opts, runner, sl.strip_ansi(text)

    def test_card_shows_the_facts_and_a_tip(self):
        self.map_pane()
        self.put_state({"state": "working", "since": 1700000000, "ctx_pct": 32, "limit_pct": 19, "cost": 160.7,
                        "model": "Opus 5.5", "effort": "max", "dur_s": 28200, "lines_add": 563, "lines_del": 4,
                        "dir": "nostromo"})
        p = self.run_handler(self.url("card"))
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        opts, runner, text = self.popup()
        lines = text.rstrip("\n").split("\n")
        self.assertTrue(lines[0].startswith("agent · working for "), lines)
        self.assertEqual(lines[1], "Opus 5.5 · effort max")
        self.assertEqual(lines[2], "context 32% · limit 19% · $160.70 · 7h50m")
        self.assertEqual(lines[3], "+563/-4 · dir nostromo")
        self.assertEqual(lines[4], "")
        self.assertTrue(lines[5].startswith("tip: "), lines)
        self.assertEqual(lines[6], "any key closes · m: menu")
        self.assertEqual(opts["-T"], " agent ")
        self.assertEqual(opts["-h"], str(len(lines) + 2))
        self.assertLessEqual(int(opts["-w"]), 78)
        self.assertIn("read -rsn1 k", runner)
        self.assertIn("printf '\\033[?1000h\\033[?1006h'", runner)
        self.assertIn('[ "$k" = m ] && exit 10', runner)
        self.assertEqual(self.tmux_calls("display-menu"), [])

    def test_card_without_facts_still_opens(self):
        self.map_pane()
        p = self.run_handler(self.url("card"))
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        _, _, text = self.popup()
        self.assertTrue(text.startswith("agent · no status yet\n"), text)
        self.assertIn("tip: ", text)

    def test_card_uses_the_agent_name_and_m_opens_the_menu_after(self):
        self.write_config("RETRO_HUD_AGENT_NAME=Nova\n")
        self.map_pane()
        p = self.run_handler(self.url("card", sock="/tmp/tmux-1000/default"), FAKE_TMUX_POPUP_RC="10")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        pops = self.tmux_calls("display-popup")
        self.assertEqual(len(pops), 1)
        self.assertIn(" Nova ", pops[0])
        client, title, items = self.menu()          # m: the menu opens once the popup is closed
        self.assertEqual(title, "Nova")
        self.assertEqual([i[0] for i in items][:2], ["status card", "wave"])
        self.assertTrue(all(c[:2] == ["-S", "/tmp/tmux-1000/default"] for c in self.log("tmux")), self.log("tmux"))

    def test_card_needs_a_mapped_claude_pane(self):
        p = self.run_handler(self.url("card"))                      # no pane map
        self.assertEqual(self.tmux_calls("display-popup"), [])
        self.assertTrue(any("no agent presence" in m for m in self.messages()), self.messages())
        self.map_pane()
        self.run_handler(self.url("card"), FAKE_TMUX_PANE_CMD="vim")
        self.assertEqual(self.tmux_calls("display-popup"), [])

    def test_a_second_right_click_closes_the_popup_that_is_up(self):
        self.map_pane()
        menu_file = os.path.join(self.tmp, "m.tmux")
        mark = os.path.join(self.home, ".cache", "retro-hud", "popup-_dev_pts_3")
        os.makedirs(os.path.dirname(mark), exist_ok=True)
        with open(mark, "w") as f:
            f.write("")
        p = self.run_handler(self.url("card"), RETRO_HUD_MENU_FILE=menu_file, RETRO_HUD_CLIENT="/dev/pts/3")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        with open(menu_file) as f:
            self.assertEqual(f.read(), "display-popup -C -c '/dev/pts/3'\n")
        self.assertFalse(os.path.exists(mark))                            # consumed
        self.assertEqual(self.tmux_calls("display"), [])                  # nothing else ran
        # a stale marker is ignored and cleared: the cloud opens as usual
        with open(mark, "w") as f:
            f.write("")
        os.utime(mark, (0, 0))
        p = self.run_handler(self.url("card"), RETRO_HUD_MENU_FILE=menu_file, RETRO_HUD_CLIENT="/dev/pts/3")
        with open(menu_file) as f:
            line = f.read()
        self.assertTrue(line.startswith("display-popup -c '/dev/pts/3' -x M"), line)
        self.assertFalse(os.path.exists(mark))
        # every popup runner keeps the marker while it runs
        runner_path = re.search(r"cloud\.[A-Za-z0-9]+\.sh", line).group(0)
        with open(os.path.join(self.home, ".cache", "retro-hud", runner_path)) as f:
            runner = f.read()
        self.assertIn("touch '" + mark + "'", runner)
        self.assertIn("trap 'rm -f '" + "\\''" + mark + "'\\''" + "' EXIT", runner)

    def test_card_inside_the_binding_is_a_speech_cloud_at_the_pointer(self):
        self.map_pane()
        self.put_state({"state": "working", "since": 1700000000, "ctx_pct": 32, "limit_pct": 19, "cost": 160.7,
                        "model": "Opus 5.5", "effort": "max", "dur_s": 28200})
        menu_file = os.path.join(self.tmp, "m.tmux")
        with open(menu_file, "w") as f:
            f.write("stale\n")
        p = self.run_handler(self.url("card"), RETRO_HUD_MENU_FILE=menu_file, RETRO_HUD_CLIENT="/dev/pts/3")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(self.tmux_calls("display-popup"), [])          # nothing runs here
        with open(menu_file) as f:
            line = f.read()
        self.assertTrue(line.startswith("display-popup -c '/dev/pts/3' -x M -y '#{popup_mouse_y}' -w "), line)  # above the creature
        self.assertIn("-b rounded", line)
        runner_path = re.search(r"cloud\.[A-Za-z0-9]+\.sh", line)
        self.assertTrue(runner_path, line)
        with open(os.path.join(self.home, ".cache", "retro-hud", runner_path.group(0))) as f:
            runner = f.read()
        cat = re.search(r"cat '([^']+)'", runner)
        with open(cat.group(1)) as f:
            text = sl.strip_ansi(f.read())
        lines = text.rstrip("\n").split("\n")
        self.assertTrue(lines[0].startswith("agent · working for "), lines)
        self.assertEqual(lines[1], "context 32% · limit 19% · $160.70 · 7h50m")
        self.assertEqual(lines[2], "m menu · c card · click or key closes")
        self.assertEqual(len(lines), 3)                                  # highlights only
        self.assertIn("-h 5 ", line)
        self.assertIn("printf '\\033[?1000h\\033[?1006h'\nwhile IFS= read -rsn1 k </dev/tty; do", runner)  # a click closes it too
        self.assertIn("case \"$s\" in '[<'*m) continue ;; esac", runner)                                    # a release does not
        self.assertIn("run-shell -b -d 0.3", runner)
        self.assertIn("retro-hud://agent?pane=%257", runner)
        self.assertIn("retro-hud://card?pane=%257", runner)
        self.assertIn("rm -f", runner)

    def test_local_extension_may_render_the_card_itself(self):
        self.map_pane()
        ext = os.path.join(self.home, ".claude", "retro-hud-handler.local.sh")
        os.makedirs(os.path.dirname(ext), exist_ok=True)
        with open(ext, "w") as f:
            f.write('case "$1" in retro-hud://card*) echo "mine: $1" > "$HOME/ext.out"; exit 0 ;; esac\n')
        p = self.run_handler(self.url("card"))
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        with open(os.path.join(self.home, "ext.out")) as f:
            self.assertEqual(f.read().strip(), "mine: retro-hud://card?pane=%257")
        self.assertEqual(self.tmux_calls("display-popup"), [])
        self.run_handler(self.url("agent"))                          # anything else falls through
        self.assertEqual(len(self.tmux_calls("display-menu")), 1)


class TestAgentEndToEnd(ShellHarness):
    """HUD → pane map → handler → state/events files → HUD. The handler
    stamps real time, so the HUD renders at real time too."""
    SID = "e2e-session"
    ENV = ("RETRO_HUD_ACTIONS", "TMUX_PANE", "TMUX", "RETRO_HUD_CACHE_DIR")

    def setUp(self):
        super().setUp()
        self._saved = {k: os.environ.pop(k, None) for k in self.ENV}
        self.cache = os.path.join(self.home, ".cache", "retro-hud")
        os.environ["RETRO_HUD_CACHE_DIR"] = self.cache
        os.environ["RETRO_HUD_ACTIONS"] = "1"
        os.environ["TMUX_PANE"] = "%7"
        self.t0 = int(time.time())
        self.transcript = os.path.join(self.tmp, "t.jsonl")
        with open(self.transcript, "w") as f:
            f.write(json.dumps(user(self.t0 - 30)) + "\n")
            f.write(json.dumps(asst(self.t0 - 2, "tool_use", ("tool_use",))) + "\n")

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        super().tearDown()

    def row1(self, dt=0):
        p = copy.deepcopy(MINIMAL)
        p["transcript_path"] = self.transcript
        p["session_id"] = self.SID
        return sl.strip_ansi(sl.render(p, 160, self.t0 + dt)[0])

    def has(self, plain, sprite_set, mood):
        return any(f in plain for f in sl.SPRITES[sprite_set][mood])

    def test_menu_actions_reach_the_hud(self):
        self.row1()  # writes the state file and the pane map
        self.run_handler(self.url("agent"))
        self.assertEqual(len(self.tmux_calls("display-menu")), 1)

        self.run_handler("do", "agent", "%7", "sprite", "ghost")
        self.assertTrue(self.has(self.row1(1), "ghost", "working"))
        self.run_handler("do", "agent", "%7", "sprite", "default")
        self.assertTrue(self.has(self.row1(2), "alien", "working"))

        with open(os.path.join(self.cache, self.SID + ".events.jsonl"), "a") as f:
            f.write(json.dumps({"ts": self.t0, "text": "hello there", "ttl": 120}) + "\n")
        self.assertIn("hello there", self.row1(3))
        self.run_handler("do", "agent", "%7", "quiet")
        self.assertNotIn("hello", self.row1(4))
        with open(os.path.join(self.cache, self.SID + ".state.json")) as f:
            self.assertGreaterEqual(json.load(f)["mute_until"], self.t0 + 3600)

        self.run_handler("do", "agent", "%7", "wave")
        plain = self.row1(int(time.time()) - self.t0 + 1)
        self.assertTrue(self.has(plain, "alien", "yours"), plain)
        self.assertNotIn("wave", plain)

        self.run_handler("do", "agent", "%7", "status")
        msg = self.tmux_calls("display-message")[-1][-1]
        self.assertIn("working", msg)
        self.assertIn("ctx 0%", msg)


    def test_reroll_reaches_the_creature(self):
        os.environ["RETRO_HUD_CREATURE"] = "tall"
        try:
            p = copy.deepcopy(MINIMAL)
            p["transcript_path"] = self.transcript
            p["session_id"] = self.SID
            sl.render(copy.deepcopy(p), 160, self.t0 + 100)  # records `creature`
            self.run_handler(self.url("agent"))
            labels = [i[0] for i in self.menu()[2]]
            self.assertIn("reroll", labels)
            self.run_handler("do", "agent", "%7", "reroll")
            with open(os.path.join(self.cache, self.SID + ".state.json")) as f:
                seed = json.load(f)["seed"]
            self.assertIn("RETRO_HUD_CREATURE_SEED={}".format(seed),
                          self.tmux_calls("display-message")[-1][-1])
            after = sl.render(copy.deepcopy(p), 160, self.t0 + 100)
            os.environ["RETRO_HUD_CREATURE_SEED"] = str(seed)
            with open(os.path.join(self.cache, self.SID + ".state.json")) as f:
                st = json.load(f)
            st.pop("seed")
            with open(os.path.join(self.cache, self.SID + ".state.json"), "w") as f:
                json.dump(st, f)
            self.assertEqual(sl.render(copy.deepcopy(p), 160, self.t0 + 100)[:2], after[:2])
        finally:
            os.environ["RETRO_HUD_CREATURE"] = "0"
            os.environ.pop("RETRO_HUD_CREATURE_SEED", None)

class TestHooksOnlyInstall(ShellHarness):
    def test_hooks_only_leaves_statusline_and_settings_statusline_alone(self):
        home = self.home
        claude = os.path.join(home, ".claude")
        os.makedirs(claude, exist_ok=True)
        with open(os.path.join(claude, "statusline.py"), "w") as f:
            f.write("# local edits\n")
        with open(os.path.join(claude, "statusline-command.sh"), "w") as f:
            f.write("#!/bin/bash\n# local wrapper\n")
        settings = os.path.join(claude, "settings.json")
        with open(settings, "w") as f:
            json.dump({"statusLine": {"type": "command", "command": "x", "refreshInterval": 1},
                       "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "keep"}]}]}}, f)
        p = subprocess.run(["bash", os.path.join(REPO, "install.sh"), "--hooks-only"],
                           env=self.env(), capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(open(os.path.join(claude, "statusline.py")).read(), "# local edits\n")
        self.assertIn("local wrapper", open(os.path.join(claude, "statusline-command.sh")).read())
        data = json.load(open(settings))
        self.assertEqual(data["statusLine"]["refreshInterval"], 1)
        self.assertEqual(data["statusLine"]["command"], "x")
        self.assertIn("Stop", data["hooks"])
        self.assertEqual(data["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "keep")
        self.assertTrue(os.path.exists(os.path.join(claude, "presence-hook.sh")))
        self.assertNotIn("Installed retro-hud", p.stdout)


class TestHandlerInstall(ShellHarness):
    DESKTOP = os.path.join(".local", "share", "applications", "retro-hud-url-handler.desktop")

    def sh(self, script, *args, **extra):
        env = self.env(extra)
        env["PATH"] = self.bin + ":" + env["PATH"]   # fakes first; real python3 stays reachable
        return subprocess.run(["bash", os.path.join(REPO, script)] + list(args), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)

    def path(self, rel):
        return os.path.join(self.home, rel)

    def read(self, rel):
        with open(self.path(rel)) as f:
            return f.read()

    def mime_owner(self):
        p = self.path(".fake-mime")
        return open(p).read() if os.path.exists(p) else ""

    def test_handler_only_installs_and_registers(self):
        p = self.sh("install.sh", "--handler-only")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        dest = self.path(".claude/retro-hud-handler.sh")
        self.assertEqual(self.read(".claude/retro-hud-handler.sh"), open(HANDLER).read())
        self.assertTrue(os.access(dest, os.X_OK))
        desktop = self.read(self.DESKTOP)
        self.assertIn('Exec="{}" %u'.format(dest), desktop)
        self.assertIn("MimeType=x-scheme-handler/retro-hud;", desktop)
        self.assertEqual(self.mime_owner(), "retro-hud-url-handler.desktop")
        self.assertTrue(self.log("update-desktop-database"))
        # statusline untouched
        self.assertFalse(os.path.exists(self.path(".claude/statusline.py")))
        self.assertFalse(os.path.exists(self.path(".claude/settings.json")))
        # settings file: commented defaults only, so it changes nothing
        cfg = self.read(".config/retro-hud/env")
        self.assertIn("# RETRO_HUD_MODELS=opus,sonnet,haiku", cfg)
        self.assertIn("# RETRO_HUD_USAGE_URL=https://claude.ai/settings/usage", cfg)
        self.assertTrue(all(not l.strip() or l.startswith("#") for l in cfg.splitlines()))
        out = p.stdout.decode()
        self.assertIn('set -as terminal-features "xterm*:hyperlinks"', out)
        self.assertIn("RETRO_HUD_ACTIONS=1", out)

    def test_no_hyperlink_hint_when_tmux_has_it(self):
        p = self.sh("install.sh", "--handler-only",
                    FAKE_TMUX_FEATURES="terminal-features[2] xterm*:hyperlinks")
        self.assertNotIn("terminal-features", p.stdout.decode())

    def test_existing_scheme_owner_is_left_alone(self):
        with open(self.path(".fake-mime"), "w") as f:
            f.write("someone-else.desktop")
        p = self.sh("install.sh", "--handler-only")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertIn("someone-else.desktop", p.stdout.decode())
        self.assertEqual(self.mime_owner(), "someone-else.desktop")
        self.assertFalse(os.path.exists(self.path(self.DESKTOP)))
        self.assertNotIn(["default", "retro-hud-url-handler.desktop", "x-scheme-handler/retro-hud"],
                         self.log("xdg-mime"))
        self.assertTrue(os.path.exists(self.path(".claude/retro-hud-handler.sh")))

    def test_rerun_keeps_user_settings(self):
        self.sh("install.sh", "--handler-only")
        self.write_config("RETRO_HUD_MODELS=fable\n")
        p = self.sh("install.sh", "--handler-only")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(self.read(".config/retro-hud/env"), "RETRO_HUD_MODELS=fable\n")

    def test_handler_flag_also_installs_statusline(self):
        p = self.sh("install.sh", "--handler")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        for rel in (".claude/statusline.py", ".claude/settings.json",
                    ".claude/retro-hud-handler.sh", self.DESKTOP):
            self.assertTrue(os.path.exists(self.path(rel)), rel)

    def test_plain_install_registers_nothing(self):
        p = self.sh("install.sh")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertTrue(os.path.exists(self.path(".claude/statusline.py")))
        self.assertFalse(os.path.exists(self.path(".claude/retro-hud-handler.sh")))
        self.assertFalse(os.path.exists(self.path(self.DESKTOP)))
        self.assertEqual(self.log("xdg-mime"), [])

    def mimeapps(self, text=None):
        p = self.path(".config/mimeapps.list")
        if text is not None:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(text)
        return open(p).read()

    def test_uninstall_round_trip(self):
        self.sh("install.sh", "--handler")
        # what a real xdg-mime writes
        self.mimeapps("[Default Applications]\nx-scheme-handler/retro-hud="
                      "retro-hud-url-handler.desktop\ntext/plain=editor.desktop\n")
        p = self.sh("uninstall.sh")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        for rel in (".claude/statusline.py", ".claude/retro-hud-handler.sh", self.DESKTOP):
            self.assertFalse(os.path.exists(self.path(rel)), rel)
        self.assertEqual(self.mimeapps(),
                         "[Default Applications]\ntext/plain=editor.desktop\n")
        self.assertTrue(os.path.exists(self.path(".config/retro-hud/env")))  # user settings kept
        self.assertIn("retro-hud/env", p.stdout.decode())

    def test_uninstall_leaves_a_foreign_desktop_entry(self):
        os.makedirs(os.path.dirname(self.path(self.DESKTOP)))
        foreign = "[Desktop Entry]\nExec=/opt/other/handler %u\n"
        with open(self.path(self.DESKTOP), "w") as f:
            f.write(foreign)
        self.mimeapps("[Default Applications]\nx-scheme-handler/retro-hud="
                      "retro-hud-url-handler.desktop\n")
        p = self.sh("uninstall.sh")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(self.read(self.DESKTOP), foreign)
        self.assertIn("x-scheme-handler/retro-hud=", self.mimeapps())
class TestAgentState(unittest.TestCase):
    """agent_state(): the transcript tail → what the agent is doing."""

    def state(self, entries, now=NOW):
        return sl.agent_state(entries, now)[0]

    def test_unknown_without_message_entries(self):
        self.assertEqual(sl.agent_state([], NOW), ("unknown", 0))
        self.assertEqual(self.state([{"type": "last-prompt"}, {"type": "mode"}]), "unknown")

    def test_end_turn_is_yours(self):
        self.assertEqual(sl.agent_state([user(NOW - 20), asst(NOW - 5)], NOW),
                         ("yours", NOW - 5))

    def test_tool_use_and_user_entries_are_working(self):
        self.assertEqual(self.state([asst(NOW - 3, "tool_use", ("tool_use",))]), "working")
        self.assertEqual(self.state([asst(NOW - 9), user(NOW - 2)]), "working")
        self.assertEqual(self.state([asst(NOW - 9, "tool_use"), result(NOW - 1)]), "working")

    def test_null_stop_reason_is_still_streaming(self):
        self.assertEqual(self.state([user(NOW - 9), asst(NOW - 1, None)]), "working")

    def test_turn_ending_stop_reasons_are_yours(self):
        # synthetic API-error replies end the turn with stop_sequence
        for stop in ("stop_sequence", "max_tokens", "refusal"):
            self.assertEqual(self.state([asst(NOW - 1, stop)]), "yours", stop)

    def test_idle_and_asleep_thresholds(self):
        self.assertEqual(self.state([asst(NOW - 599)]), "yours")
        self.assertEqual(sl.agent_state([asst(NOW - 600)], NOW), ("idle", NOW - 600))
        self.assertEqual(self.state([asst(NOW - 3599)]), "idle")
        self.assertEqual(self.state([asst(NOW - 3600)]), "asleep")
        # thresholds are parameters (the env knobs feed them)
        self.assertEqual(sl.agent_state([asst(NOW - 120)], NOW, idle_s=60)[0], "idle")
        self.assertEqual(sl.agent_state([asst(NOW - 120)], NOW, sleep_s=100)[0], "asleep")

    def test_non_message_types_skipped(self):
        noise = [{"type": t, "timestamp": iso(NOW)} for t in
                 ("attachment", "system", "last-prompt", "api-request",
                  "file-history-snapshot", "mode", "queue-operation")]
        # api-request-blob carries a full message but is not a message entry
        noise.append({"type": "api-request-blob",
                      "message": {"stop_reason": "tool_use", "content": []}})
        self.assertEqual(self.state([asst(NOW - 5)] + noise), "yours")

    def test_meta_and_harness_entries_are_not_the_user(self):
        for text in ("<command-name>/clear</command-name>",
                     "<local-command-stdout>ok</local-command-stdout>",
                     "<local-command-caveat>Caveat: ...</local-command-caveat>"):
            self.assertEqual(self.state([asst(NOW - 5), user(NOW - 1, text)]), "yours", text)
        self.assertEqual(self.state([asst(NOW - 5), user(NOW - 1, meta=True)]), "yours")
        # the marker test is a prefix test only
        self.assertEqual(self.state([asst(NOW - 5), user(NOW - 1, "see <command-name>")]),
                         "working")

    def test_string_content_is_handled(self):
        e = user(NOW - 1)
        e["message"]["content"] = "<command-name>/model</command-name>"
        self.assertEqual(self.state([asst(NOW - 5), e]), "yours")
        e["message"]["content"] = "plain prompt"
        self.assertEqual(self.state([asst(NOW - 5), e]), "working")

    def test_interrupt_hands_the_turn_back(self):
        self.assertEqual(self.state([asst(NOW - 5, "tool_use"),
                                     user(NOW - 1, "[Request interrupted by user]")]),
                         "yours")

    def test_error_burst(self):
        burst = [result(NOW - 40, True), result(NOW - 10, True), asst(NOW - 8, "tool_use")]
        self.assertEqual(sl.agent_state(burst, NOW), ("error", NOW - 10))
        # held 30 s from the newest error, then released
        self.assertEqual(self.state(burst, NOW + 19), "error")
        self.assertEqual(self.state(burst, NOW + 20), "working")

    def test_single_error_is_not_a_flinch(self):
        self.assertEqual(self.state([result(NOW - 5, True), asst(NOW - 4, "tool_use")]),
                         "working")
        # two errors more than 60 s apart are not a burst either
        self.assertEqual(self.state([result(NOW - 75, True), result(NOW - 5, True)]),
                         "working")
        # is_error None / False never count
        self.assertEqual(self.state([result(NOW - 5, None), result(NOW - 4, None)]),
                         "working")

    def test_malformed_entries_skipped(self):
        bad = [None, 3, "x", {"type": "user"}, {"type": "assistant", "timestamp": "nope"},
               {"type": "user", "timestamp": iso(NOW), "message": "str"}]
        self.assertEqual(self.state([asst(NOW - 5)] + bad), "yours")

    def test_parse_ts(self):
        self.assertEqual(sl.parse_ts(iso(NOW)), NOW)
        self.assertAlmostEqual(sl.parse_ts("2027-01-15T08:00:00.250Z"),
                               sl.parse_ts("2027-01-15T08:00:00Z") + 0.25)
        for bad in (None, "", "yesterday", 5):
            self.assertIsNone(sl.parse_ts(bad))


class TestTranscriptTail(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=_SUITE_TMP)
        self.path = os.path.join(self.dir, "t.jsonl")

    def write(self, lines):
        with open(self.path, "w") as f:
            for e in lines:
                f.write((e if isinstance(e, str) else json.dumps(e)) + "\n")

    def test_missing_file(self):
        self.assertEqual(sl.tail_entries(os.path.join(self.dir, "nope")), ([], 0))
        self.assertEqual(sl.tail_entries(""), ([], 0))

    def test_reads_entries_in_order(self):
        self.write([user(NOW - 9), "{broken", asst(NOW - 1)])
        entries, n = sl.tail_entries(self.path)
        self.assertEqual([e["type"] for e in entries], ["user", "assistant"])
        self.assertEqual(n, os.path.getsize(self.path))

    def test_huge_file_reads_only_the_tail(self):
        pad = {"type": "attachment", "blob": "x" * 2000}
        self.write([user(NOW - 99)] + [pad] * 2000 + [asst(NOW - 5)])
        self.assertGreater(os.path.getsize(self.path), 3 * 1024 * 1024)
        entries, n = sl.tail_entries(self.path)
        self.assertEqual(n, sl.TAIL_BYTES)
        self.assertEqual(sl.agent_state(entries, NOW)[0], "yours")
        # the partial first line is dropped, never mis-parsed
        self.assertTrue(all(isinstance(e, dict) for e in entries))

    def test_partial_first_line_dropped(self):
        # the 64 KB cut lands inside an older message line: it must not count
        cut = asst(NOW - 9, "tool_use")
        cut["pad"] = "x" * (sl.TAIL_BYTES + 10)
        self.write([cut, user(NOW - 3)])
        entries, n = sl.tail_entries(self.path)
        self.assertEqual(n, sl.TAIL_BYTES)
        self.assertEqual([e["type"] for e in entries], ["user"])

    def test_big_newest_entry_widens_the_tail(self):
        # one line bigger than the 64 KB floor (a large tool result, an
        # api-request-shape) must not blind the reader
        big = {"type": "api-request-shape", "blob": "y" * (sl.TAIL_BYTES + 5000)}
        self.write([{"type": "attachment", "blob": "z" * 3000}] * 400 +
                   [asst(NOW - 5), big])
        entries, n = sl.tail_entries(self.path)
        self.assertGreater(n, sl.TAIL_BYTES)
        self.assertLessEqual(n, sl.TAIL_MAX)
        self.assertEqual(sl.agent_state(entries, NOW)[0], "yours")


class TestMoods(unittest.TestCase):
    MOODS = ("calm", "agitated", "red", "error", "working", "yours", "needs",
             "idle", "asleep")

    def test_every_sprite_set_has_every_mood_at_width_5(self):
        self.assertEqual(set(sl.SPRITES), {"alien", "cat", "robot", "ghost"})
        for name, moods in sl.SPRITES.items():
            self.assertEqual(set(moods), set(self.MOODS), name)
            for mood, frames in moods.items():
                self.assertEqual(len(frames), 2, (name, mood))
                for f in frames:
                    self.assertEqual(sl.vwidth(f), 5, (name, mood, f))
                    self.assertTrue(f.isprintable() and f.isascii(), (name, mood, f))
            # each mood owns a first frame no other mood in the set uses
            firsts = [moods[m][0] for m in self.MOODS]
            self.assertEqual(len(set(firsts)), len(firsts), name)
        for m in self.MOODS:
            self.assertIn(m, sl.MOOD_SPEEDS)
            self.assertIn(m, sl.MOOD_COLORS)

    def test_alien_keeps_its_gauge_frames(self):
        a = sl.SPRITES["alien"]
        self.assertEqual((a["calm"], a["agitated"], a["red"]), sl.ALIEN_FRAMES)

    def test_mood_precedence(self):
        table = [
            # (worst gauge %, agent state, mood)
            (95, "error", "red"),        # red-zone gauge beats everything
            (95, "working", "red"),
            (50, "error", "error"),      # then a burst of errors
            (80, "error", "error"),
            (80, "working", "agitated"),  # then an agitated gauge
            (80, "needs", "agitated"),
            (50, "needs", "needs"),      # then what the agent is doing
            (50, "working", "working"),
            (50, "yours", "yours"),
            (50, "idle", "idle"),
            (50, "asleep", "asleep"),
            (50, "unknown", "calm"),     # else calm
            (0, None, "calm"),
        ]
        for pct, state, want in table:
            self.assertEqual(sl.pick_mood(pct, state), want, (pct, state))


class TestFrameBubble(unittest.TestCase):
    ROW = sl.NEON_GREEN + "┌─" + sl.R + "x" * 20

    def frame(self, cols, mood="working", bubble="", now=NOW, since=NOW, sprite="alien"):
        pres = {"mood": mood, "bubble": bubble, "since": since, "sprite": sprite}
        return sl._frame(self.ROW, cols, "┐", True, 50, now, pres)

    def test_frame_math_unchanged_with_a_bubble(self):
        for mood in TestMoods.MOODS:
            for bubble in ("", "ready", "y" * 18, "日本語のふきだし"):
                for cols in range(24, 241, 7):
                    for now in (NOW, NOW + 10, NOW + 170, NOW + 3333):
                        row = self.frame(cols, mood, bubble, now)
                        plain = sl.strip_ansi(row)
                        bare = sl.strip_ansi(sl._frame(self.ROW, cols, "┐", True))
                        self.assertEqual(sl.vislen(row), cols, (mood, bubble, cols, now))
                        self.assertEqual(sl.vwidth(plain), sl.vwidth(bare))
                        self.assertEqual(plain[:23], bare[:23])  # row + leading space
                        self.assertTrue(plain.endswith("┐"), (mood, bubble, cols))

    def test_bubble_sits_beside_the_sprite(self):
        plain = sl.strip_ansi(self.frame(120, "yours", "ready", NOW))
        self.assertRegex(plain, r"(\\\^\.\^/|/\^\.\^\\)╴ready─|ready╶(\\\^\.\^/|/\^\.\^\\)")

    def test_bubble_flips_side_at_the_end_of_the_rule(self):
        # sweep a whole patrol: the full bubble is always shown
        for now in range(NOW, NOW + 3000, 10):
            plain = sl.strip_ansi(self.frame(80, "working", "ready", now))
            self.assertIn("ready", plain, now)

    def test_bubble_shrinks_on_a_short_rule_and_drops_when_no_room(self):
        # a 10-cell track (the minimum for a sprite) leaves 5 rule cells
        base = sl.vislen(self.ROW) + 2
        for now in range(NOW, NOW + 200, 10):
            plain = sl.strip_ansi(self.frame(base + 10, "working", "abcdefgh", now))
            self.assertIn("ab", plain)
            self.assertNotIn("abcdefgh", plain)
        # below that, no sprite and no bubble
        plain = sl.strip_ansi(self.frame(base + 9, "working", "abcdefgh"))
        self.assertNotIn("o.o", plain)
        self.assertNotIn("ab", plain)

    def test_parked_moods_hold_still(self):
        spots = {sl.strip_ansi(self.frame(120, "needs", "", NOW + d, since=NOW)).find("o.o?")
                 for d in (20, 500, 4000)}
        self.assertEqual(len(spots), 1)
        self.assertNotIn(-1, spots)

    def test_yours_waves_in_place_then_cruises(self):
        spots = {sl.strip_ansi(self.frame(120, "yours", "", NOW + d, since=NOW)).find("^.^")
                 for d in (0, 10, 20)}
        self.assertEqual(len(spots), 1)
        later = {sl.strip_ansi(self.frame(120, "yours", "", NOW + d, since=NOW)).find("^.^")
                 for d in (40, 50, 60, 70)}
        self.assertGreater(len(later), 1)

    def test_sprite_set_used(self):
        plain = sl.strip_ansi(self.frame(120, "calm", "", NOW, sprite="robot"))
        self.assertTrue("[o_o]" in plain or "[-_-]" in plain)
        # an unknown set falls back to the alien
        plain = sl.strip_ansi(self.frame(120, "calm", "", NOW, sprite="dragon"))
        self.assertTrue("/o.o\\" in plain or "/-.-\\" in plain)


_KNOBS = ("RETRO_HUD_PRESENCE", "RETRO_HUD_SPRITE", "RETRO_HUD_AGENT_NAME",
          "RETRO_HUD_QUIPS", "RETRO_HUD_IDLE_MIN", "RETRO_HUD_SLEEP_MIN",
          "RETRO_HUD_ALIEN")


class PresenceCase(unittest.TestCase):
    """A temp cache dir and transcript per test; knobs restored after."""
    SID = "0d7e5c1a-session"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir=_SUITE_TMP)
        self.cache = os.path.join(self.tmp, "cache")
        self._saved_cache = os.environ["RETRO_HUD_CACHE_DIR"]
        os.environ["RETRO_HUD_CACHE_DIR"] = self.cache
        self.transcript = os.path.join(self.tmp, "t.jsonl")

    def tearDown(self):
        os.environ["RETRO_HUD_CACHE_DIR"] = self._saved_cache
        for k in _KNOBS:
            os.environ.pop(k, None)

    def tx(self, *entries):
        with open(self.transcript, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def payload(self, base=MINIMAL, sid=None):
        p = copy.deepcopy(base)
        p["transcript_path"] = self.transcript
        p["session_id"] = self.SID if sid is None else sid
        return p

    def row1(self, now=NOW, base=MINIMAL, cols=160, sid=None):
        return sl.strip_ansi(sl.render(self.payload(base, sid), cols, now)[0])

    def path(self, suffix):
        return os.path.join(self.cache, self.SID + suffix)

    def state_file(self):
        with open(self.path(".state.json")) as f:
            return json.load(f)

    def put_state(self, **kw):
        os.makedirs(self.cache, exist_ok=True)
        with open(self.path(".state.json"), "w") as f:
            json.dump(kw, f)

    def events(self, *evs):
        os.makedirs(self.cache, exist_ok=True)
        with open(self.path(".events.jsonl"), "a") as f:
            for e in evs:
                f.write((e if isinstance(e, str) else json.dumps(e)) + "\n")

    def hooks(self, *lines):
        os.makedirs(self.cache, exist_ok=True)
        with open(self.path(".hooks.jsonl"), "a") as f:
            for ln in lines:
                f.write(json.dumps(ln) + "\n")


class TestPresenceRender(PresenceCase):
    def test_unknown_state_is_the_gauge_alien_and_touches_nothing(self):
        # no transcript on disk → exactly the 2.7 output, no cache files
        for cols in (60, 100, 160, 220):
            self.assertEqual(sl.render(self.payload(FULL), cols, NOW),
                             sl.render(copy.deepcopy(FULL), cols, NOW))
        self.assertFalse(os.path.exists(self.cache))

    def test_working_agent_hustles(self):
        self.tx(user(NOW - 9), asst(NOW - 2, "tool_use", ("tool_use",)))
        self.assertIn("/o.o/", self.row1(NOW))
        self.assertIn("\\o.o\\", self.row1(NOW + 10))

    def test_presence_off_restores_the_gauge_alien(self):
        self.tx(asst(NOW - 2, "tool_use"))
        os.environ["RETRO_HUD_PRESENCE"] = "0"
        for cols in (100, 160):
            self.assertEqual(sl.render(self.payload(FULL), cols, NOW),
                             sl.render(copy.deepcopy(FULL), cols, NOW))
        self.assertFalse(os.path.exists(self.cache))

    def test_alien_zero_grounds_everything(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.events({"ts": NOW, "text": "hello", "ttl": 30})
        os.environ["RETRO_HUD_ALIEN"] = "0"
        plain = self.row1(NOW)
        self.assertNotIn("o.o", plain)
        self.assertNotIn("hello", plain)
        self.assertFalse(os.path.exists(self.path(".state.json")))

    def test_rows_1_and_2_unchanged_with_presence_on(self):
        # Presence may only redraw the top rule: row 2 is byte-identical,
        # row 1's segments are identical, and the rule keeps its length.
        self.tx(user(NOW - 50), asst(NOW - 2, "tool_use"))
        self.events({"ts": NOW - 1, "text": "deploy finished", "ttl": 600})
        for cols in range(50, 241, 10):
            for t in (NOW, NOW + 10, NOW + 30):
                on = sl.render(self.payload(FULL), cols, t)
                os.environ["RETRO_HUD_PRESENCE"] = "0"
                off = sl.render(self.payload(FULL), cols, t)
                del os.environ["RETRO_HUD_PRESENCE"]
                self.assertEqual(on[1], off[1], cols)
                p_on, p_off = sl.strip_ansi(on[0]), sl.strip_ansi(off[0])
                self.assertEqual(sl.vislen(on[0]), sl.vislen(off[0]), cols)
                # the gauge alien's rule holds no spaces: the last one is
                # where the segments end and the rule begins
                m = re.match(r"^(.*) [^ ]*┐$", p_off)
                segs = m.group(1) if m else p_off
                self.assertTrue(p_on.startswith(segs + (" " if m else "")), cols)
                self.assertEqual(p_on[-1], p_off[-1])

    def test_sprite_set_from_env_and_state_file(self):
        self.tx(asst(NOW - 2, "tool_use"))
        os.environ["RETRO_HUD_SPRITE"] = "cat"
        self.assertIn("=^.^/", self.row1(NOW))
        self.put_state(sprite="ghost")
        self.assertIn("(o.o~", self.row1(NOW))

    def test_hostile_session_id_writes_nothing(self):
        self.tx(asst(NOW - 2, "tool_use"))
        plain = self.row1(NOW, sid="../../escape")
        self.assertIn("/o.o/", plain)  # the transcript still drives the mood
        self.assertFalse(os.path.exists(self.cache))

    def test_unwritable_cache_dir_means_no_bubble_and_no_crash(self):
        blocker = os.path.join(self.tmp, "file-not-dir")
        with open(blocker, "w") as f:
            f.write("x")
        os.environ["RETRO_HUD_CACHE_DIR"] = os.path.join(blocker, "sub")
        self.tx(asst(NOW - 2, "tool_use"))
        self.row1(NOW)
        self.tx(asst(NOW + 5))
        plain = self.row1(NOW + 6)
        self.assertIn("^.^", plain)
        self.assertNotIn("╴", plain)
        self.assertNotIn("╶", plain)

    def test_no_subprocess_in_statusline(self):
        with open(sl.__file__) as f:
            src = f.read()
        self.assertIsNone(re.search(r"^\s*(import|from)\s+(subprocess|pty)\b", src, re.M))
        for banned in ("subprocess.", "os.system(", "os.popen(", "os.exec", "os.spawn",
                       "os.fork("):
            self.assertNotIn(banned, src)


class TestAgentLink(PresenceCase):
    """With click actions on, the sprite (never its bubble) links to the
    agent menu, and the HUD maps the tmux pane to its session id."""
    ENV = ("RETRO_HUD_ACTIONS", "TMUX_PANE", "TMUX")

    def setUp(self):
        super().setUp()
        self._saved_env = {k: os.environ.pop(k, None) for k in self.ENV}

    def tearDown(self):
        for k, v in self._saved_env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        super().tearDown()

    def actions_on(self, pane="%7"):
        os.environ["RETRO_HUD_ACTIONS"] = "1"
        os.environ["TMUX_PANE"] = pane
        os.environ["TMUX"] = "/tmp/tmux-1000/default,4242,0"

    def agent_links(self, row):
        return re.findall(r"\x1b\]8;;(retro-hud://card[^\x07]*)\x07(.*?)\x1b\]8;;\x07", row)

    def name_links(self, row):
        return re.findall(r"\x1b\]8;;(retro-hud://agent[^\x07]*)\x07(.*?)\x1b\]8;;\x07", row)

    def test_sprite_is_linked_and_the_bubble_is_not(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.events({"ts": NOW, "text": "deploy finished", "ttl": 600})
        self.actions_on()
        row = sl.render(self.payload(), 160, NOW)[0]
        (url, text), = self.agent_links(row)
        self.assertEqual(url, "retro-hud://card?pane=%257&sock=/tmp/tmux-1000/default")
        self.assertIn(sl.strip_ansi(text), sl.SPRITES["alien"]["working"])
        self.assertIn("deploy finished", sl.strip_ansi(row))
        self.assertNotIn("deploy", "".join(t for _, t in self.agent_links(row)))

    def test_no_agent_link_outside_tmux_or_when_off(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.assertEqual(self.agent_links(sl.render(self.payload(), 160, NOW)[0]), [])
        os.environ["RETRO_HUD_ACTIONS"] = "1"
        self.assertEqual(self.agent_links(sl.render(self.payload(), 160, NOW)[0]), [])

    def test_session_name_segment_can_shrink_or_go(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.actions_on()
        for mode, want in (("icon", "◈"), ("1", "◈ polish-the-hud"), ("0", None)):
            os.environ["RETRO_HUD_SESSION_NAME"] = mode
            payload = self.payload()
            payload["session_name"] = "polish-the-hud"
            rows = sl.render(payload, 160, NOW)
            links = self.name_links(rows[0])
            if want is None:
                self.assertEqual(links, [], mode)
                self.assertNotIn("◈", sl.strip_ansi(rows[0]))
            else:
                self.assertEqual([sl.strip_ansi(t) for _, t in links], [want], (mode, rows[0]))
        os.environ.pop("RETRO_HUD_SESSION_NAME", None)

    def test_session_name_segment_links_to_the_agent_menu(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.actions_on()
        payload = self.payload()
        payload["session_name"] = "nova"
        rows = sl.render(payload, 160, NOW)
        links = self.name_links(rows[0])
        self.assertEqual([u for u, _ in links], ["retro-hud://agent?pane=%257&sock=/tmp/tmux-1000/default"])
        self.assertEqual(sl.strip_ansi(links[0][1]), "◈ nova")
        self.assertEqual(self.name_links(rows[0] + rows[1]), links)
        # the creature is the card's link, never the menu's
        self.assertTrue(all(u.startswith("retro-hud://card?") for u, _ in self.agent_links(rows[0])))

    def test_state_file_carries_the_card_facts(self):
        self.tx(asst(NOW - 2, "tool_use"))
        payload = self.payload(FULL)
        sl.render(payload, 160, NOW)
        st = self.state_file()
        self.assertEqual(st["model"], "Fable 5")
        self.assertEqual(st["effort"], "high")
        self.assertEqual(st["dur_s"], 5432)
        self.assertEqual((st["lines_add"], st["lines_del"]), (128, 37))
        self.assertEqual(st["dir"], "some-long-project-name")
        facts = sl.card_facts({"model": {"id": "claude-x"}, "cost": {"total_duration_ms": "bad"}})
        self.assertEqual(facts, {"model": "claude-x"})

    def test_links_never_change_the_top_rule(self):
        self.tx(user(NOW - 50), asst(NOW - 2, "tool_use"))
        self.events({"ts": NOW - 1, "text": "deploy finished", "ttl": 600})
        self.actions_on()
        for payload in (MINIMAL, FULL, OVERLOAD):
            for cols in range(50, 241, 10):
                for t in (NOW, NOW + 10, NOW + 30):
                    os.environ["RETRO_HUD_ACTIONS"] = "0"
                    plain = [sl.strip_ansi(r) for r in sl.render(self.payload(payload), cols, t)]
                    os.environ["RETRO_HUD_ACTIONS"] = "1"
                    rows = sl.render(self.payload(payload), cols, t)
                    self.assertEqual([sl.strip_ansi(r) for r in rows], plain, (cols, t))
                    self.assertEqual(sl.vislen(rows[0]), sl.vislen(plain[0]))

    def test_pane_to_session_map_written_with_actions_on(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.row1(NOW)
        self.assertFalse(os.path.exists(os.path.join(self.cache, "pane-12.sid")))
        self.actions_on("%12")
        self.row1(NOW)
        with open(os.path.join(self.cache, "pane-12.sid")) as f:
            self.assertEqual(f.read(), self.SID)
        # a new session in the same pane takes the map over
        self.row1(NOW + 1, sid="another-session")
        with open(os.path.join(self.cache, "pane-12.sid")) as f:
            self.assertEqual(f.read(), "another-session")

    def test_no_map_for_a_malformed_pane(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.actions_on("%1/../x")
        self.row1(NOW)
        self.assertEqual([n for n in os.listdir(self.cache) if n.startswith("pane-")], [])

    def test_wave_event_waves_instead_of_speaking(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.row1(NOW - 1)
        self.events({"ts": NOW, "text": "wave", "ttl": 10})
        waving = set(sl.SPRITES["alien"]["yours"])
        for t in (NOW, NOW + 5, NOW + 9):
            plain = self.row1(t)
            self.assertTrue(any(f in plain for f in waving), (t, plain))
            self.assertNotIn("wave", plain)
        plain = self.row1(NOW + 10)  # expired: back to work
        self.assertFalse(any(f in plain for f in waving), plain)
        self.assertTrue(any(f in plain for f in sl.SPRITES["alien"]["working"]), plain)

    def test_wave_uses_the_chosen_sprite_set(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.put_state(sprite="robot")
        self.events({"ts": NOW, "text": "wave", "ttl": 10})
        plain = self.row1(NOW + 1)
        self.assertTrue(any(f in plain for f in sl.SPRITES["robot"]["yours"]), plain)

    def test_red_gauge_still_beats_a_wave(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.events({"ts": NOW, "text": "wave", "ttl": 10})
        plain = self.row1(NOW + 1, base=OVERLOAD)
        self.assertTrue(any(f in plain for f in sl.SPRITES["alien"]["red"]), plain)


class TestBubbles(PresenceCase):
    def test_state_file_snapshot(self):
        self.tx(asst(NOW - 2, "tool_use"))
        sl.render(self.payload(FULL), 160, NOW)
        s = self.state_file()
        self.assertEqual(s["state"], "working")
        self.assertAlmostEqual(s["since"], NOW - 2)
        self.assertEqual((s["ctx_pct"], s["limit_pct"], s["cost"]), (72, 81, 3.21))
        self.assertEqual(sorted(os.listdir(self.cache)), [self.SID + ".state.json"])

    def test_ready_once_per_transition(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.assertNotIn("ready", self.row1(NOW))
        self.tx(asst(NOW - 2, "tool_use"), asst(NOW + 4))
        for t in (NOW + 5, NOW + 20, NOW + 34):
            self.assertIn("╴ready", self.row1(t).replace("ready╶", "╴ready"), t)
        for t in (NOW + 36, NOW + 60, NOW + 200):
            self.assertNotIn("ready", self.row1(t), t)

    def test_first_sight_is_not_a_transition(self):
        self.tx(asst(NOW - 2))
        self.assertNotIn("ready", self.row1(NOW))

    def test_agent_name_prefixes_state_bubbles(self):
        os.environ["RETRO_HUD_AGENT_NAME"] = "Nova"
        self.tx(asst(NOW - 2, "tool_use"))
        self.row1(NOW)
        self.tx(asst(NOW + 1))
        self.assertIn("Nova: ready", self.row1(NOW + 2))

    def test_error_bubble(self):
        self.tx(asst(NOW - 9, "tool_use"))
        self.row1(NOW)
        self.tx(result(NOW + 1, True), result(NOW + 3, True))
        plain = self.row1(NOW + 4)
        self.assertIn("hm.", plain)
        self.assertIn("/>.<\\", plain)

    def test_gauge_crossings(self):
        self.tx(asst(NOW - 2, "tool_use"))
        hot = copy.deepcopy(MINIMAL)
        hot["context_window"] = {"used_percentage": 85}
        self.row1(NOW, base=hot)
        hot["context_window"]["used_percentage"] = 92
        self.assertIn("compact?", self.row1(NOW + 5, base=hot))
        warm = copy.deepcopy(MINIMAL)
        warm["rate_limits"] = {"five_hour": {"used_percentage": 60}}
        self.row1(NOW + 100, base=warm)
        warm["rate_limits"]["five_hour"]["used_percentage"] = 71
        self.assertIn("limit soon", self.row1(NOW + 105, base=warm))

    def test_mute(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.row1(NOW)
        s = self.state_file()
        s["mute_until"] = NOW + 3600
        self.put_state(**s)
        self.events({"ts": NOW, "text": "hello there", "ttl": 60})
        self.tx(asst(NOW + 1))
        plain = self.row1(NOW + 2)
        self.assertNotIn("ready", plain)
        self.assertNotIn("hello", plain)
        self.assertEqual(self.state_file()["mute_until"], NOW + 3600)  # preserved

    def test_mute_expires(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.put_state(state="working", since=NOW - 2, mute_until=NOW + 10)
        self.events({"ts": NOW + 5, "text": "hello there", "ttl": 60})
        self.assertNotIn("hello", self.row1(NOW + 9))
        self.assertIn("hello there", self.row1(NOW + 11))

    def test_events_beat_state_bubbles_and_expire(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.row1(NOW)
        self.tx(asst(NOW + 1))
        self.events({"ts": NOW, "text": "tests green", "ttl": 20})
        plain = self.row1(NOW + 2)
        self.assertIn("tests green", plain)
        self.assertNotIn("ready", plain)
        # once the event expires the still-fresh state bubble shows
        self.assertIn("ready", self.row1(NOW + 21))
        self.assertNotIn("tests green", self.row1(NOW + 21))

    def test_newest_unexpired_event_wins(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.events({"ts": NOW - 5, "text": "first", "ttl": 100},
                    "{garbage", {"ts": NOW - 1, "text": "second", "ttl": 100},
                    {"ts": NOW - 50, "text": "stale", "ttl": 10},
                    {"ts": NOW - 1, "text": 7}, ["not", "a", "dict"])
        self.assertIn("second", self.row1(NOW))
        # an expired newer event falls back to the older live one
        self.events({"ts": NOW, "text": "gone", "ttl": 0})
        plain = self.row1(NOW + 1)
        self.assertNotIn("gone", plain)
        self.assertIn("second", plain)

    def test_event_default_ttl(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.events({"ts": NOW, "text": "no ttl given"})
        self.assertIn("no ttl given", self.row1(NOW + 29))
        self.assertNotIn("no ttl given", self.row1(NOW + 31))

    def test_event_text_sanitized_and_clamped(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.events({"ts": NOW, "text": "a\x1b[31mb\x07c\nd" + "z" * 40, "ttl": 60})
        row = sl.render(self.payload(), 160, NOW)[0]
        self.assertNotIn("\x07", row)
        self.assertNotIn("\x1b[31m", row)
        plain = sl.strip_ansi(row)
        m = re.search(r"╴([^─]+)|([^─ ]+)╶", plain)
        text = m.group(1) or m.group(2)
        self.assertTrue(text.startswith("a[31mbcd"), text)
        self.assertEqual(sl.vwidth(text), sl.BUBBLE_MAX)
        self.assertEqual(sl.vislen(row), 160)

    def test_idle_quip_then_ambient_z(self):
        self.tx(asst(NOW - 1000))
        self.put_state(state="idle", since=NOW - 1000)
        plain = self.row1(NOW)
        quip = [q for q in sl.QUIPS if q in plain]
        self.assertEqual(len(quip), 1, plain)
        self.assertIn("z", self.row1(NOW + 31))          # ambient doze
        self.assertFalse([q for q in sl.QUIPS if q in self.row1(NOW + 600)])
        self.assertTrue([q for q in sl.QUIPS if q in self.row1(NOW + 1201)])

    def test_quips_off(self):
        os.environ["RETRO_HUD_QUIPS"] = "0"
        self.tx(asst(NOW - 1000))
        self.put_state(state="idle", since=NOW - 1000)
        plain = self.row1(NOW)
        self.assertFalse([q for q in sl.QUIPS if q in plain])
        self.assertRegex(plain, r"╴z─|─z╶")

    def test_asleep_ambient(self):
        self.tx(asst(NOW - 4000))
        self.put_state(state="asleep", since=NOW - 4000)
        plain = self.row1(NOW)
        self.assertIn("/_._\\", plain)
        self.assertRegex(plain, r"╴zZ─|─zZ╶")

    def test_quip_pool(self):
        self.assertGreaterEqual(len(sl.QUIPS), 12)
        for q in sl.QUIPS:
            self.assertLessEqual(sl.vwidth(q), sl.BUBBLE_MAX, q)
            self.assertTrue(q.isprintable() and q.isascii(), q)

    def test_idle_threshold_env(self):
        os.environ["RETRO_HUD_IDLE_MIN"] = "1"
        os.environ["RETRO_HUD_QUIPS"] = "0"
        self.tx(asst(NOW - 90))
        self.assertIn("/-_-\\", self.row1(NOW))
        os.environ["RETRO_HUD_SLEEP_MIN"] = "1"
        self.assertIn("/_._\\", self.row1(NOW))

    def test_old_files_pruned_once(self):
        os.makedirs(self.cache)
        old = NOW - 8 * 86400
        names = ["a.state.json", "b.events.jsonl", "c.hooks.jsonl", "keep.txt",
                 "fresh.state.json"]
        for n in names:
            p = os.path.join(self.cache, n)
            open(p, "w").close()
            t = NOW - 60 if n == "fresh.state.json" else old
            os.utime(p, (t, t))
        self.tx(asst(NOW - 2, "tool_use"))
        sl.render(self.payload(), 160, NOW)
        left = sorted(os.listdir(self.cache))
        self.assertEqual(left, sorted(["keep.txt", "fresh.state.json",
                                       self.SID + ".state.json"]))
        self.assertEqual(self.state_file()["last_prune"], NOW)


class TestBubbleModes(PresenceCase):
    """RETRO_HUD_BUBBLES: alerts (default) never narrates; off says nothing."""

    def setUp(self):
        super().setUp()
        self._mode = os.environ.pop("RETRO_HUD_BUBBLES", None)

    def tearDown(self):
        os.environ.pop("RETRO_HUD_BUBBLES", None)
        if self._mode is not None:
            os.environ["RETRO_HUD_BUBBLES"] = self._mode
        super().tearDown()

    @staticmethod
    def snap(state, ctx=10, limit=10):
        return {"state": state, "ctx_pct": ctx, "limit_pct": limit, "cost": 1.0}

    def test_default_is_alerts_no_narration(self):
        prev = self.snap("working")
        self.assertEqual(sl.next_bubble(prev, self.snap("yours"), NOW, name="Nova")[0], "")
        self.assertEqual(sl.next_bubble(prev, self.snap("error"), NOW)[0], "")
        self.assertEqual(sl.next_bubble(self.snap("idle"), self.snap("idle"), NOW)[0], "")
        self.assertEqual(sl.next_bubble(self.snap("asleep"), self.snap("asleep"), NOW)[0], "")
        prev = dict(self.snap("idle"), last_quip=0)
        self.assertEqual(sl.next_bubble(prev, self.snap("idle"), NOW + 10 * sl.QUIP_EVERY_S)[0], "")

    def test_alerts_still_speak(self):
        prev = self.snap("working")
        self.assertEqual(sl.next_bubble(prev, self.snap("needs"), NOW, name="Nova")[0], "Nova: need you")
        self.assertEqual(sl.next_bubble(prev, self.snap("working", ctx=95), NOW)[0], "compact?")
        self.assertEqual(sl.next_bubble(prev, self.snap("working", limit=75), NOW)[0], "limit soon")
        self.assertEqual(sl.next_bubble(prev, self.snap("working"), NOW, event="deploy done")[0], "deploy done")

    def test_all_restores_narration(self):
        prev = self.snap("working")
        self.assertEqual(sl.next_bubble(prev, self.snap("yours"), NOW, mode="all")[0], "ready")
        self.assertEqual(sl.next_bubble(prev, self.snap("error"), NOW, mode="all")[0], "hm.")
        self.assertEqual(sl.next_bubble(self.snap("asleep"), self.snap("asleep"), NOW, mode="all")[0], "zZ")

    def test_off_says_nothing_even_events(self):
        prev = self.snap("working")
        self.assertEqual(sl.next_bubble(prev, self.snap("needs"), NOW, mode="off")[0], "")
        self.assertEqual(sl.next_bubble(prev, self.snap("working"), NOW, event="hi", mode="off")[0], "")

    def test_default_through_the_bar(self):
        # End to end with the environment default: a finished turn draws no "ready".
        self.tx(asst(NOW - 2, "tool_use"))
        self.row1(NOW)
        self.tx(asst(NOW - 2, "tool_use"), asst(NOW + 4))
        for t in (NOW + 5, NOW + 20):
            self.assertNotIn("ready", self.row1(t), t)
        os.environ["RETRO_HUD_BUBBLES"] = "all"
        self.tx(asst(NOW - 2, "tool_use"))
        self.row1(NOW + 100)
        self.tx(asst(NOW - 2, "tool_use"), asst(NOW + 104))
        self.assertIn("ready", self.row1(NOW + 105))


class TestHooksMerge(PresenceCase):
    def test_merge_rules(self):
        m = sl.merge_hooks
        # newer hook wins over the transcript
        self.assertEqual(m("working", NOW - 20, [(NOW - 10, "needs", "")], NOW),
                         ("needs", NOW - 10))
        # older hook loses
        self.assertEqual(m("working", NOW - 5, [(NOW - 10, "yours", "")], NOW),
                         ("working", NOW - 5))
        # an idle_prompt does not paper over a pending permission prompt
        self.assertEqual(m("working", NOW - 100,
                           [(NOW - 90, "needs", ""), (NOW - 30, "yours", "idle_prompt")],
                           NOW), ("needs", NOW - 90))
        # … but does once the transcript moved past the prompt
        self.assertEqual(m("working", NOW - 60,
                           [(NOW - 90, "needs", ""), (NOW - 30, "yours", "idle_prompt")],
                           NOW)[0], "yours")
        # a run of the same state keeps its first timestamp, and decays
        self.assertEqual(m("working", NOW - 900,
                           [(NOW - 700, "yours", ""), (NOW - 640, "yours", "idle_prompt")],
                           NOW), ("idle", NOW - 700))
        # an error burst is never overridden
        self.assertEqual(m("error", NOW - 5, [(NOW - 1, "yours", "")], NOW),
                         ("error", NOW - 5))
        # hooks alone are enough when the transcript is unreadable
        self.assertEqual(m("unknown", 0, [(NOW - 3, "working", "")], NOW),
                         ("working", NOW - 3))
        # nothing usable → unchanged
        self.assertEqual(m("yours", NOW - 5, [], NOW), ("yours", NOW - 5))

    def test_read_hooks(self):
        self.hooks({"ts": NOW - 3, "state": "working"},
                   {"ts": NOW - 1.5, "state": "needs"},
                   {"ts": "x", "state": "yours"}, {"ts": NOW, "state": "dancing"},
                   {"ts": NOW, "state": "yours", "src": "idle_prompt"})
        self.assertEqual(sl.read_hooks(self.path(".hooks.jsonl")),
                         [(NOW - 3, "working", ""), (NOW - 1.5, "needs", ""),
                          (NOW, "yours", "idle_prompt")])
        self.assertEqual(sl.read_hooks(self.path(".nope")), [])

    def test_permission_prompt_beckons_in_render(self):
        self.tx(asst(NOW - 20, "tool_use", ("tool_use",)))
        self.row1(NOW - 15)
        self.hooks({"ts": NOW - 10, "state": "needs"})
        plain = self.row1(NOW)
        self.assertIn("o.o?", plain)
        self.assertIn("need you", plain)
        # the tool result after approval puts it back to work
        self.tx(asst(NOW - 20, "tool_use", ("tool_use",)), result(NOW + 5))
        self.assertIn("/o.o/", self.row1(NOW + 10).replace("\\o.o\\", "/o.o/"))


HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "presence-hook.sh")


class TestPresenceHook(unittest.TestCase):
    """presence-hook.sh: a Claude Code hook appending one JSON line."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir=_SUITE_TMP)
        self.cache = os.path.join(self.tmp, "cache")

    def run_hook(self, stdin, *args, cache=None):
        env = dict(os.environ, RETRO_HUD_CACHE_DIR=cache or self.cache)
        return subprocess.run(["bash", HOOK] + list(args), input=stdin.encode(),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env, timeout=10)

    def lines(self, sid):
        with open(os.path.join(self.cache, sid + ".hooks.jsonl")) as f:
            return [json.loads(l) for l in f]

    def test_appends_state_line_silently(self):
        before = time.time()
        p = self.run_hook('{"session_id":"abc-1","hook_event_name":"Notification",'
                          '"prompt":"say \\"session_id\\":\\"evil\\""}', "needs")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, b"", b""))
        p = self.run_hook('{"session_id": "abc-1", "hook_event_name": "Stop"}', "yours")
        got = self.lines("abc-1")
        self.assertEqual([g["state"] for g in got], ["needs", "yours"])
        for g in got:
            self.assertGreaterEqual(g["ts"], int(before))
            self.assertLessEqual(g["ts"], time.time() + 1)
        hooks = sl.read_hooks(os.path.join(self.cache, "abc-1.hooks.jsonl"))
        self.assertEqual([h[1] for h in hooks], ["needs", "yours"])

    def test_state_from_the_event_when_no_argument(self):
        cases = [('{"session_id":"s","hook_event_name":"Stop"}', "yours", ""),
                 ('{"session_id":"s","hook_event_name":"UserPromptSubmit"}', "working", ""),
                 ('{"session_id":"s","hook_event_name":"Notification",'
                  '"notification_type":"permission_prompt"}', "needs", ""),
                 ('{"session_id":"s","hook_event_name":"Notification",'
                  '"notification_type":"idle_prompt"}', "yours", "idle_prompt")]
        for stdin, _, _ in cases:
            self.assertEqual(self.run_hook(stdin).returncode, 0)
        got = self.lines("s")
        self.assertEqual([(g["state"], g.get("src", "")) for g in got],
                         [(c[1], c[2]) for c in cases])
        # an unrelated notification records nothing
        self.run_hook('{"session_id":"s","hook_event_name":"Notification",'
                      '"notification_type":"auth_success"}')
        self.assertEqual(len(self.lines("s")), 4)

    def test_never_fails_never_speaks(self):
        blocker = os.path.join(self.tmp, "file")
        open(blocker, "w").close()
        for stdin, args, cache in (("{not json", ("yours",), None),
                                   ("", ("yours",), None),
                                   ('{"session_id":"../../x"}', ("yours",), None),
                                   ('{"session_id":"ok"}', ("bogus",), None),
                                   ('{"session_id":"ok"}', ("yours",),
                                    os.path.join(blocker, "sub"))):
            p = self.run_hook(stdin, *args, cache=cache)
            self.assertEqual((p.returncode, p.stdout), (0, b""), (stdin, args))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "x.hooks.jsonl")))
        self.assertFalse(os.path.exists(os.path.join(self.cache, "ok.hooks.jsonl")))


class TestInstallHooks(unittest.TestCase):
    """install.sh --hooks against a throwaway HOME."""

    def setUp(self):
        self.home = tempfile.mkdtemp(dir=_SUITE_TMP)
        self.claude = os.path.join(self.home, ".claude")
        os.makedirs(self.claude)
        self.settings = os.path.join(self.claude, "settings.json")
        with open(self.settings, "w") as f:
            json.dump({"env": {"X": "1"}, "hooks": {"Stop": [
                {"hooks": [{"type": "command", "command": "echo mine"}]}]}}, f)

    def sh(self, script, *args):
        env = dict(os.environ, HOME=self.home)
        return subprocess.run(["bash", os.path.join(HERE, script)] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env, timeout=30)

    def load(self):
        with open(self.settings) as f:
            return json.load(f)

    def ours(self, data):
        found = []
        for event, groups in data.get("hooks", {}).items():
            for g in groups:
                for h in g.get("hooks", []):
                    if "presence-hook.sh" in h.get("command", ""):
                        found.append((event, g.get("matcher", ""), h["command"]))
        return sorted(found)

    def test_plain_install_adds_no_hooks(self):
        p = self.sh("install.sh")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(self.ours(self.load()), [])

    def test_hooks_merge_idempotently_with_backup(self):
        for _ in range(2):
            p = self.sh("install.sh", "--hooks")
            self.assertEqual(p.returncode, 0, p.stderr.decode())
        data = self.load()
        hook = os.path.join(self.claude, "presence-hook.sh")
        self.assertTrue(os.path.isfile(hook))
        self.assertEqual([(e, m) for e, m, _ in self.ours(data)],
                         [("Notification", "idle_prompt"),
                          ("Notification", "permission_prompt"),
                          ("Stop", ""), ("UserPromptSubmit", "")])
        cmds = {(e, m): c for e, m, c in self.ours(data)}
        self.assertTrue(cmds[("Stop", "")].endswith("presence-hook.sh yours"))
        self.assertTrue(cmds[("UserPromptSubmit", "")].endswith(" working"))
        self.assertTrue(cmds[("Notification", "permission_prompt")].endswith(" needs"))
        self.assertTrue(cmds[("Notification", "idle_prompt")].endswith(" yours idle_prompt"))
        # the user's own hook and settings survive
        self.assertIn({"hooks": [{"type": "command", "command": "echo mine"}]},
                      data["hooks"]["Stop"])
        self.assertEqual(data["env"], {"X": "1"})
        self.assertIn("statusLine", data)
        backups = [n for n in os.listdir(self.claude) if n.startswith("settings.json.bak")]
        self.assertGreaterEqual(len(backups), 1)

    def test_uninstall_removes_only_our_hooks(self):
        self.sh("install.sh", "--hooks")
        p = self.sh("uninstall.sh")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        data = self.load()
        self.assertEqual(self.ours(data), [])
        self.assertEqual(data["hooks"]["Stop"],
                         [{"hooks": [{"type": "command", "command": "echo mine"}]}])
        self.assertNotIn("Notification", data["hooks"])
        self.assertFalse(os.path.exists(os.path.join(self.claude, "presence-hook.sh")))


def _connected(grid):
    cells = {(r, c) for r in range(len(grid)) for c in range(len(grid[0])) if grid[r][c]}
    if not cells:
        return False
    start = min(cells)
    seen, todo = {start}, [start]
    while todo:
        r, c = todo.pop()
        for n in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if n in cells and n not in seen:
                seen.add(n)
                todo.append(n)
    return seen == cells


class TestCreatureGrid(unittest.TestCase):
    SEEDS = list(range(200)) + [2 ** 32 - 1, 123456789]

    def check(self, g, label):
        self.assertEqual(len(g), 4, label)
        for row in g:
            self.assertEqual(len(row), 9, label)
            self.assertTrue(all(v in (None, "body", "eye") for v in row), label)
            self.assertEqual(list(row), list(reversed(row)), label)  # mirrored
        self.assertTrue(_connected(g), label)
        eyes = [(r, c) for r in range(4) for c in range(9) if g[r][c] == "eye"]
        self.assertEqual(len(eyes), 2, label)
        (r1, c1), (r2, c2) = sorted(eyes)
        self.assertEqual((r1, r2), (1, 1), label)
        self.assertEqual(c1 + c2, 8, label)
        self.assertTrue(any(g[1][c] == "body" for c in range(c1 + 1, c2)), label)
        self.assertGreaterEqual(sum(1 for v in g[3] if v), 2, label)

    def test_every_family_and_seed_is_well_formed(self):
        self.assertEqual(sl.FAMILIES, ("blob", "beast", "alien", "bot", "robot"))
        for fam in sl.FAMILIES:
            for seed in self.SEEDS:
                self.check(sl.creature_grid(seed, fam), (fam, seed))

    def test_deterministic_and_varied(self):
        for fam in sl.FAMILIES:
            self.assertEqual(sl.creature_grid(7, fam), sl.creature_grid(7, fam))
            shapes = {sl.creature_grid(s, fam) for s in range(60)}
            self.assertGreater(len(shapes), 5, fam)
        # families look different from each other for the same seed
        self.assertGreater(len({sl.creature_grid(3, f) for f in sl.FAMILIES}), 1)

    def test_fallback_body_when_attempts_run_out(self):
        self.check(sl.FALLBACK_GRID, "fallback")
        for fam in sl.FAMILIES:
            if fam != "robot":  # built from parts, never grown: no fallback
                self.assertEqual(sl.creature_grid(5, fam, attempts=0), sl.FALLBACK_GRID)

    def test_unknown_family_is_the_alien(self):
        self.assertEqual(sl.creature_grid(9, "dragon"), sl.creature_grid(9, "alien"))

    def test_leg_counts_per_family(self):
        def legs(row):
            runs, prev = 0, None
            for v in row:
                if v and not prev:
                    runs += 1
                prev = v
            return runs
        for seed in range(60):
            self.assertEqual(legs(sl.creature_grid(seed, "alien")[3]), 3, seed)
            self.assertEqual(legs(sl.creature_grid(seed, "beast")[3]), 2, seed)
            self.assertEqual(legs(sl.creature_grid(seed, "bot")[3]), 2, seed)
            self.assertIn(legs(sl.creature_grid(seed, "robot")[3]), (1, 2), seed)  # a pole or treads: 1


class TestRobotGrid(unittest.TestCase):
    """The robot family's 12×8 body: parts picked by the seed, mirrored,
    one piece, eyes on the eye row only."""
    PARTS = {"antenna": ("one", "two", "dish", "ears", "flat"), "eyes": ("squares", "visor", "dots"),
             "neck": (True, False), "arms": ("down", "out", "up", "none"),
             "chest": ("panel", "lights", "plain"), "legs": ("legs", "treads", "pole"),
             "head": (6, 8, 10), "torso": (8, 10, 12)}

    def check(self, g, label):
        self.assertEqual(len(g), sl.ROBOT_ROWS, label)
        for row in g:
            self.assertEqual(len(row), sl.ROBOT_COLS, label)
            self.assertTrue(all(v in (None, "body", "eye", "hole") for v in row), label)
            self.assertEqual(list(row), list(reversed(row)), label)  # mirrored
        self.assertTrue(_connected(g), label)
        eyes = sorted((r, c) for r in range(sl.ROBOT_ROWS) for c in range(sl.ROBOT_COLS)
                      if g[r][c] == "eye")
        self.assertTrue(eyes, label)
        self.assertEqual({r for r, _ in eyes}, {2}, label)            # the eye row
        self.assertTrue(all(g[1][c] == "body" for _, c in eyes), label)  # under the head top
        holes = [(r, c) for r in range(sl.ROBOT_ROWS) for c in range(sl.ROBOT_COLS)
                 if g[r][c] == "hole"]
        self.assertTrue(all(r == 5 for r, _ in holes), label)           # chest only
        for r in (6, 7):                                                 # legs, treads or a pole
            self.assertGreaterEqual(sum(1 for v in g[r] if v == "body"), 2, label)
        self.assertGreaterEqual(sum(1 for v in g[1] if v == "body"), 6, label)  # a head

    def test_every_seed_is_well_formed(self):
        for seed in TestCreatureGrid.SEEDS:
            self.check(sl.robot_grid(seed), seed)

    def test_parts_from_the_seed_cover_every_option(self):
        seen = {k: set() for k in self.PARTS}
        for seed in range(300):
            parts = sl.robot_parts(seed)
            self.assertEqual(set(parts), set(self.PARTS), seed)
            for k, v in parts.items():
                self.assertIn(v, self.PARTS[k], (seed, k))
                seen[k].add(v)
            self.assertEqual(sl.robot_parts(seed), parts)
        for k, opts in self.PARTS.items():
            self.assertEqual(seen[k], set(opts), k)

    def test_parts_show_in_the_body(self):
        for seed in range(120):
            g, parts = sl.robot_grid(seed), sl.robot_parts(seed)
            label = (seed, parts)
            eyes = [c for c in range(sl.ROBOT_COLS) if g[2][c] == "eye"]
            if parts["eyes"] == "visor":
                self.assertEqual(eyes, list(range(eyes[0], eyes[-1] + 1)), label)  # one slot
                self.assertEqual(len(eyes), parts["head"] - 2, label)
            else:
                self.assertEqual(len(eyes), 4 if parts["eyes"] == "squares" else 2, label)
            self.assertEqual(sum(1 for v in g[1] if v), parts["head"], label)
            self.assertEqual(sum(1 for v in g[4] if v) >= parts["torso"], True, label)
            if parts["neck"]:  # a neck, plus the arm tips beside it when raised
                self.assertEqual(sum(1 for v in g[3] if v), 2 + (2 if parts["arms"] == "up" else 0),
                                 label)
            if parts["legs"] == "treads":
                self.assertEqual(sum(1 for v in g[7] if v), sl.ROBOT_COLS, label)
            elif parts["legs"] == "pole":
                self.assertEqual(sum(1 for v in g[6] if v), 2, label)
            else:
                self.assertEqual(sum(1 for v in g[6] if v), 4, label)
            self.assertEqual(bool([c for c in range(sl.ROBOT_COLS) if g[5][c] == "hole"]),
                             parts["chest"] != "plain", label)
            if parts["arms"] == "none":
                self.assertEqual([sum(1 for v in row if v) for row in g[4:6]],
                                 [parts["torso"]] * 2, label)
            else:
                self.assertTrue(any(g[r][0] for r in (3, 4, 5)), label)  # an arm reaches the edge

    def test_deterministic_and_varied(self):
        self.assertEqual(sl.robot_grid(7), sl.robot_grid(7))
        self.assertGreater(len({sl.robot_grid(s) for s in range(200)}), 60)

    def test_four_row_body_is_a_small_robot_with_the_same_parts(self):
        # at 4 rows (tiny, and the half-block pose) the same parts at 10×4 / 9×4:
        # antenna row, head with two eye holes, body (arms out or not), legs
        for seed in range(80):
            parts = sl.robot_parts(seed)
            for width in (9, 10):
                g = sl.creature_grid(seed, "robot", width=width)
                label = (seed, width, parts)
                TestCreatureGrid.check(self, g, label) if width == 9 else TestTinyGrid.check(self, g, label)
                self.assertTrue(any(g[0]), label)                        # something on top
                self.assertEqual(sum(1 for v in g[1] if v), (8 if parts["head"] > 6 else 6) - (10 - width),
                                 label)
                arms = parts["arms"] != "none"
                self.assertEqual(bool(g[2][0]) and bool(g[2][-1]), arms, label)
                last = sum(1 for v in g[3] if v)
                if parts["legs"] == "treads":
                    self.assertEqual(last, width, label)
                elif parts["legs"] == "pole":
                    self.assertEqual(last, width - 6, label)          # a short base
                else:
                    self.assertEqual(last, 4 if parts["torso"] >= 10 else 2, label)
            self.assertEqual(sl.creature_grid(seed, "robot", attempts=0), sl.creature_grid(seed, "robot"))
        self.assertGreater(len({sl.creature_grid(s, "robot", width=10) for s in range(120)}), 20)
        self.assertEqual(sl.creature_family("robot"), "robot")
        self.assertEqual(sl.creature_family("bot"), "bot")


class TestTinyGrid(unittest.TestCase):
    """The braille creature's body: the same generator at width 10."""

    def check(self, g, label):
        self.assertEqual(len(g), 4, label)
        for row in g:
            self.assertEqual(len(row), 10, label)
            self.assertEqual(list(row), list(reversed(row)), label)
        self.assertTrue(_connected(g), label)
        eyes = sorted((r, c) for r in range(4) for c in range(10) if g[r][c] == "eye")
        self.assertEqual(len(eyes), 2, label)
        self.assertEqual((eyes[0][0], eyes[1][0]), (1, 1), label)
        self.assertEqual(eyes[0][1] + eyes[1][1], 9, label)
        self.assertGreaterEqual(sum(1 for v in g[3] if v), 2, label)

    def test_every_family_and_seed_is_well_formed(self):
        for fam in sl.FAMILIES:
            for seed in TestCreatureGrid.SEEDS:
                self.check(sl.creature_grid(seed, fam, width=10), (fam, seed))
        self.check(sl.FALLBACK_TINY, "fallback")
        self.assertEqual(sl.creature_grid(5, "bot", attempts=0, width=10), sl.FALLBACK_TINY)

    def test_same_family_shape_as_the_big_one(self):
        # the centre column is doubled; everything else is the 9-wide body
        for fam in sl.FAMILIES:
            for seed in range(30):
                big, tiny = sl.creature_grid(seed, fam), sl.creature_grid(seed, fam, width=10)
                for r in range(4):
                    self.assertEqual(tiny[r][:5], big[r][:5], (fam, seed))


class TestBraille(unittest.TestCase):
    BITS = ((1, 8), (2, 16), (4, 32), (64, 128))

    def test_each_dot_has_its_bit(self):
        for r in range(4):
            for c in range(2):
                dots = [[None, None] for _ in range(4)]
                dots[r][c] = "b"
                self.assertEqual(sl.braille(dots), [chr(0x2800 + self.BITS[r][c])])

    def test_full_empty_and_width(self):
        full = [["b"] * 4 for _ in range(4)]
        self.assertEqual(sl.braille(full), ["⣿", "⣿"])
        self.assertEqual(sl.braille([[None] * 14 for _ in range(4)]), [None] * 7)
        self.assertEqual(len(sl.braille([["b"] * 14 for _ in range(4)])), 7)

    def test_eyes_are_holes(self):
        dots = [["b", "b"], ["e", "b"], ["b", "b"], ["b", "b"]]
        self.assertEqual(sl.braille(dots), [chr(0x2800 + 0xFF - 2)])

    def test_half_cell_offset_moves_one_dot(self):
        g = sl.creature_grid(0, "alien", width=10)
        dots0 = [[None] + [v if v == "body" else None for v in row] + [None] * 3 for row in g]
        dots1 = [[None] + row[:-1] for row in dots0]
        a, b = sl.braille(dots0), sl.braille(dots1)
        self.assertNotEqual(a, b)
        # the left column of each cell in offset 1 is the right column of
        # the cell before it in offset 0
        for i in range(1, 7):
            left = (ord(b[i] or "⠀") - 0x2800) & 0x47
            right = (ord(a[i - 1] or "⠀") - 0x2800) & 0xB8
            self.assertEqual(left, (right >> 3) & 0x07 | (right & 0x80) >> 1)


class TestCreatureIdentity(unittest.TestCase):
    def test_seed_sources_normalise(self):
        cs = sl.creature_seed
        self.assertEqual(cs(None, "", ""), 0)
        self.assertEqual(cs(None, "42", ""), 42)
        self.assertEqual(cs(42, "", ""), 42)              # state-file int == env "42"
        self.assertEqual(cs(None, " 42 ", ""), 42)
        self.assertEqual(cs(None, "-1", ""), 2 ** 32 - 1)  # wraps into 32 bits
        self.assertEqual(cs(None, "", "abc-session"), cs(None, "abc-session", ""))
        # stable string hash: crc32, not hash()
        self.assertEqual(cs(None, "hello", ""), 907060870)
        self.assertEqual(cs(7, "42", "sid"), 7)             # state file wins
        self.assertEqual(cs(None, "42", "sid"), 42)         # then the env
        for junk in (True, False, {"a": 1}, [1], 1.5, ""):
            self.assertEqual(cs(junk, "", "sid"), cs(None, "", "sid"), repr(junk))
        self.assertEqual(cs("12", "", ""), 12)              # a string seed in the file
        self.assertEqual(cs(2 ** 40 + 5, "", ""), 5)

    def test_color_from_seed_and_pins(self):
        cols = {sl.creature_color(s) for s in range(64)}
        self.assertEqual(cols, {198, 46, 135, 45})
        self.assertEqual(sl.creature_color(3), sl.creature_color(3))
        self.assertEqual(sl.creature_color(3, "pink"), 198)
        self.assertEqual(sl.creature_color(3, "Cyan"), 45)
        self.assertEqual(sl.creature_color(3, "208"), 208)
        self.assertEqual(sl.creature_color(3, "300"), sl.creature_color(3))
        self.assertEqual(sl.creature_color(3, "mauve"), sl.creature_color(3))

    def test_family_names_and_ascii_mapping(self):
        f = sl.creature_family
        for name in sl.FAMILIES:
            self.assertEqual(f(name), name)
        self.assertEqual((f("alien"), f("cat"), f("robot"), f("ghost")),
                         ("alien", "beast", "robot", "blob"))  # robot is its own family since 3.1
        self.assertEqual(f("dragon"), "alien")
        self.assertEqual(f(None), "alien")


_CELL_RE = re.compile(r"(?:(?:\x1b\[[0-9;]*m)*[^\x1b]\x1b\[0m)*")
MOODS_ALL = ("calm", "agitated", "red", "error", "working", "yours", "needs",
             "idle", "asleep")


def _has_color(s, n):
    """Is 256-colour index n used as a foreground or background in s?"""
    return re.search(r"[34]8;5;{}[;m]".format(n), s) is not None


def _filled(cv):
    return {(r, c) for r in range(4) for c in range(13) if cv[r][c]}


class TestMoodColour(unittest.TestCase):
    """RETRO_HUD_CREATURE_COLOR=mood: the body takes the mood's colour, the
    seeded one when calm; the gauge zones still win."""
    WANT = {"needs": 226, "error": 198, "idle": 65, "asleep": 240, "agitated": 214, "red": 196}
    SEEDED = ("calm", "working", "yours")  # the seed's colour: motion already shows these

    def test_mood_is_a_pin_value(self):
        self.assertEqual(sl.pinned_color("mood"), "mood")
        self.assertEqual(sl.pinned_color(" Mood "), "mood")
        self.assertEqual(sl.creature_color(3, "mood"), sl.creature_color(3))  # the seed's, when asked plainly
        self.assertEqual(sl.MOOD_256, self.WANT)

    def test_colour_per_mood(self):
        for seed in (0, 7, 42):
            for mood in self.SEEDED:
                self.assertEqual(sl._colour(seed, mood, "mood"), sl.creature_color(seed), mood)
            for mood, c in self.WANT.items():
                self.assertEqual(sl._colour(seed, mood, "mood"), c, mood)
            self.assertEqual(sl._colour(seed, "working", None), sl.creature_color(seed))
            self.assertEqual(sl._colour(seed, "working", 135), 135)

    def test_every_pose_takes_it(self):
        for mood, c in list(self.WANT.items()) + [(m, None) for m in self.SEEDED]:
            want = sl.creature_color(5) if c is None else c
            for fam in sl.FAMILIES:
                self.assertEqual(sl.tiny_pose(5, mood, None, NOW, 60, fam, color="mood")["body"], want,
                                 (mood, fam))
                self.assertEqual(sl.big_pose(5, mood, None, NOW, 60, fam, color="mood")["body"], want,
                                 (mood, fam))
        # the tiny alien is green on its own; with the mood colour it takes its seed's colour
        self.assertEqual(sl.tiny_pose(5, "working", None, NOW, 60, "alien")["body"], sl.TINY_ALIEN_COLOR)
        self.assertEqual(sl.tiny_pose(5, "needs", None, NOW, 60, "alien", color="mood")["body"], 226)
        self.assertEqual(sl.tiny_pose(5, "working", None, NOW, 60, "alien", color="mood")["body"],
                         sl.creature_color(5))


class QuietBody:
    """Mood poses in isolation: no blink, hop or breath this tick (the
    alive flags have their own tests)."""

    def setUp(self):
        super().setUp()
        self._flags = sl.alive_flags
        sl.alive_flags = lambda seed, tick: {"blink": False, "hop": False, "breathe": False}

    def tearDown(self):
        sl.alive_flags = self._flags
        super().tearDown()


class TestCreatureRender(unittest.TestCase):
    """Every pose fits the fixed 13-cell box on both lines."""

    def test_box_is_13_cells_on_both_lines_for_every_pose(self):
        for fam in sl.FAMILIES:
            for seed in range(0, 40, 3):
                for mood in MOODS_ALL:
                    for el in (None, 0, 3, 7, 12, 17, 25, 40, 4000):
                        for now in range(NOW, NOW + 6):
                            for icon in ("", "!", "\U0001F6A9"):
                                since = None if el is None else now - el
                                p = sl.pose(seed, mood, since, now, 60, fam, icon=icon)
                                head, rule = sl.render_box(p)
                                label = (fam, seed, mood, el, now, icon)
                                self.assertEqual(sl.vislen(head), 13, label)
                                self.assertEqual(sl.vislen(rule), 13, label)
                                self.assertTrue(_CELL_RE.fullmatch(head), label)
                                self.assertTrue(_CELL_RE.fullmatch(rule), label)

    def test_emoji_as_one_cell_keeps_the_box(self):
        saved = sl._EMOJI_W
        sl._EMOJI_W = 1
        try:
            p = sl.pose(1, "working", None, NOW, 60, icon="\U0001F6A9")
            for line in sl.render_box(p):
                self.assertEqual(sl.vislen(line), 13)
        finally:
            sl._EMOJI_W = saved

    def test_half_blocks_carry_two_pixels(self):
        flags, sl.alive_flags = sl.alive_flags, lambda s, t: {"blink": False, "hop": False,
                                                              "breathe": False}
        try:
            p = sl.pose(0, "calm", None, NOW, 60, "alien", color=46)
        finally:
            sl.alive_flags = flags
        head, rule = sl.render_box(p)
        cv = p["canvas"]
        for line, (top, bot) in ((head, (0, 1)), (rule, (2, 3))):
            plain = sl.strip_ansi(line)
            for c, ch in enumerate(plain):
                t, b = cv[top][c], cv[bot][c]
                want = "▀" if t else ("▄" if b else (" " if top == 0 else "─"))
                self.assertEqual(ch, want, (top, c))
        self.assertTrue(_has_color(head + rule, 46))   # the pinned body colour
        self.assertTrue(_has_color(head, 255))          # white eyes

    def test_steady_calm_canvas_is_the_grid(self):
        g = sl.creature_grid(5, "beast")
        quiet = next(t for t in range(NOW, NOW + 999)
                     if not any(sl.alive_flags(5, t).values()))
        cv = sl.pose(5, "calm", None, quiet, 60, "beast")["canvas"]
        for r in range(4):
            self.assertEqual([cv[r][c] for c in (0, 1, 11, 12)], [None] * 4)
            for c in range(9):
                self.assertEqual(bool(cv[r][c + 2]), bool(g[r][c]))
                self.assertEqual(cv[r][c + 2] == "e", g[r][c] == "eye")


class TestCreaturePoses(QuietBody, unittest.TestCase):
    def cv(self, mood, since=None, now=NOW, seed=4, fam="alien", **kw):
        return sl.pose(seed, mood, since, now, 60, fam, **kw)["canvas"]

    def test_working_walks_its_legs(self):
        a, b = self.cv("working", now=NOW), self.cv("working", now=NOW + 1)
        self.assertEqual(a[:3], b[:3])
        self.assertNotEqual(a[3], b[3])

    def test_yours_raises_arms_and_jumps_once(self):
        calm = self.cv("calm")
        up = self.cv("yours")
        self.assertGreater(sum(1 for v in up[1] if v), sum(1 for v in calm[1] if v))
        self.assertEqual(up[2:], calm[2:])
        self.assertFalse(any(self.cv("yours", since=NOW - 2)[3]))   # in the air
        for el in (6, 12, 40):
            self.assertTrue(any(self.cv("yours", since=NOW - el)[3]), el)

    def test_needs_bounces_with_a_yellow_question_mark(self):
        even, odd = self.cv("needs", now=NOW), self.cv("needs", now=NOW + 1)
        self.assertTrue(any(even[3]))
        self.assertFalse(any(odd[3]))
        head, _ = sl.render_box(sl.pose(4, "needs", None, NOW, 60))
        self.assertIn("?", sl.strip_ansi(head))
        self.assertTrue(_has_color(head, 226))

    def test_idle_squashes_and_blinks(self):
        self.assertFalse(any(self.cv("idle")[0]))
        # slow blinks: shut two ticks in six
        eyes = [sum(row.count("e") for row in self.cv("idle", now=NOW + i)) for i in range(6)]
        self.assertEqual(sorted(eyes), [0, 0, 2, 2, 2, 2])
        head, _ = sl.render_box(sl.pose(4, "idle", None, NOW + eyes.index(2), 60))
        self.assertTrue(_has_color(head, 244))

    def test_asleep_melts_and_empties_the_head_line(self):
        for fam in sl.FAMILIES:
            for el in (None, 1, 7, 100):
                for icon in ("", "!"):
                    p = sl.pose(9, "asleep", None if el is None else NOW - el, NOW, 60, fam,
                                icon=icon)
                    self.assertFalse(any(p["canvas"][0]) or any(p["canvas"][1]))
                    head, rule = sl.render_box(p)
                    self.assertEqual(sl.strip_ansi(head), " " * 13, (fam, el))
                    if icon:
                        self.assertIn("!", sl.strip_ansi(rule))
        calm, melt = self.cv("calm"), self.cv("asleep")
        width = lambda row: max(c for c in range(13) if row[c]) - min(c for c in range(13) if row[c])
        self.assertGreater(width(melt[3]), width(calm[3]))

    def test_error_shakes_with_x_eyes(self):
        a, b = self.cv("error", now=NOW), self.cv("error", now=NOW + 1)
        self.assertNotEqual(a, b)
        self.assertIn(b, ([[None, None] + r[:-2] for r in a], [r[2:] + [None, None] for r in a]))
        head, _ = sl.render_box(sl.pose(4, "error", None, NOW, 60, color=46))
        self.assertIn("x", sl.strip_ansi(head))
        self.assertTrue(_has_color(head, 198))          # pink x on a green body
        head, _ = sl.render_box(sl.pose(4, "error", None, NOW, 60, color=198))
        self.assertTrue(_has_color(head, 231))          # white x when the body is pink

    def test_red_zone_is_red_spins_once_then_shakes(self):
        calm = self.cv("calm")
        head, rule = sl.render_box(sl.pose(4, "red", None, NOW, 60, color=46))
        self.assertTrue(_has_color(head + rule, 196))
        self.assertFalse(_has_color(head + rule, 46))
        self.assertEqual(self.cv("red", since=NOW - 12), calm[::-1])   # upside down
        self.assertNotEqual(self.cv("red", since=NOW - 17), calm)       # edge-on
        late = self.cv("red", since=NOW - 25)
        self.assertIn(late, ([row[1:] + [None] for row in calm], [[None] + row[:-1] for row in calm]))

    def test_agitated_is_amber_with_wide_eyes(self):
        cv = self.cv("agitated")
        self.assertEqual(sum(row.count("e") for row in cv), 4)
        for c in range(13):
            if cv[1][c] == "e":
                self.assertEqual(cv[0][c], "e")
        head, rule = sl.render_box(sl.pose(4, "agitated", None, NOW, 60, color=46))
        self.assertTrue(_has_color(head + rule, 214))

    def test_unknown_mood_is_calm(self):
        self.assertEqual(self.cv("dancing"), self.cv("calm"))

    def test_scatter_on_entry_then_reassemble(self):
        for mood in MOODS_ALL:
            if mood == "red":
                continue  # spins for 20 s: its own test
            steady = self.cv(mood, since=NOW - 4000)
            for el, k in ((0, 6), (4, 6), (5, 3), (9, 3)):
                a = self.cv(mood, since=NOW - el)
                if mood == "yours" and el < 5:
                    continue  # mid-jump: the pose itself differs
                self.assertEqual(a, self.cv(mood, since=NOW - el), (mood, el))  # deterministic
                self.assertEqual(len(_filled(a)), len(_filled(steady)), (mood, el))
                rows = [r for r in range(4) if any(steady[r])]
                room = sum(1 for r in rows for v in steady[r] if not v)
                self.assertEqual(len(_filled(steady) - _filled(a)), min(k, room), (mood, el))
                self.assertTrue(all(r in rows for r, _ in _filled(a)), (mood, el))
            self.assertEqual(self.cv(mood, since=NOW - 10), steady, mood)
            self.assertEqual(self.cv(mood, since=None), steady, mood)
        # a different tick rolls a different scatter, the same tick never re-rolls
        self.assertNotEqual(self.cv("calm", since=NOW - 1, now=NOW),
                            self.cv("calm", since=NOW, now=NOW + 1))


def _tick_with(seed, **want):
    """The first tick from NOW whose alive flags match `want` (the rest off)."""
    for t in range(NOW, NOW + 5000):
        f = sl.alive_flags(seed, t)
        if all(f[k] == want.get(k, False) for k in f):
            return t
    raise AssertionError("no tick with {}".format(want))


def _width(cv):
    cols = [c for row in cv for c, v in enumerate(row) if v]
    return max(cols) - min(cols) + 1


class TestAliveFlags(unittest.TestCase):
    def test_rates_and_determinism(self):
        n = 7000
        flags = [sl.alive_flags(9, NOW + i) for i in range(n)]
        self.assertEqual(flags, [sl.alive_flags(9, NOW + i) for i in range(n)])
        blink = sum(f["blink"] for f in flags) / n
        hop = sum(f["hop"] for f in flags) / n
        self.assertAlmostEqual(blink, 1 / 7, delta=0.03)
        self.assertAlmostEqual(hop, 1 / 12, delta=0.03)
        self.assertEqual([f["breathe"] for f in flags[:8]],
                         [(NOW + i) % 4 == 0 for i in range(8)])
        # two seeds blink at different moments
        self.assertNotEqual([f["blink"] for f in flags[:200]],
                            [sl.alive_flags(10, NOW + i)["blink"] for i in range(200)])


class TestBigAlive(unittest.TestCase):
    """Blink, hop and breath on the half-block creature."""

    def cv(self, mood, t, seed=4):
        return sl.pose(seed, mood, None, t, 60, "alien")["canvas"]

    def test_blink_closes_the_eyes_for_one_tick(self):
        t = _tick_with(4, blink=True)
        self.assertEqual(sum(row.count("e") for row in self.cv("calm", t)), 0)
        self.assertEqual(sum(row.count("e") for row in self.cv("calm", _tick_with(4))), 2)
        # asleep has no eyes to blink; error keeps its x eyes
        self.assertEqual(sum(row.count("x") for row in self.cv("error", t)), 2)

    def test_hop_only_while_calm_or_working(self):
        t = _tick_with(4, hop=True)
        for mood in ("calm", "working"):
            self.assertFalse(any(self.cv(mood, t)[3]), mood)
        for mood in ("idle", "error", "agitated"):
            self.assertTrue(any(self.cv(mood, t)[3]), mood)

    def test_breathe_is_one_pixel_wider(self):
        t = _tick_with(4, breathe=True)
        q = _tick_with(4)
        self.assertEqual(_width(self.cv("calm", t)), _width(self.cv("calm", q)) + 1)


class TestCreatureMovement(unittest.TestCase):
    """Wander: ease toward a seeded target, rest, pick another; one frame
    per RETRO_HUD_TICK_S (default 1 s)."""

    def pos(self, mood, since, now, cols=60, seed=1, tick_len=1):
        return sl.pose(seed, mood, since, now, cols, tick_len=tick_len)["pos"]

    def test_moving_moods_wander_inside_the_rule(self):
        for mood, speed in (("calm", 1), ("agitated", 2), ("working", 3)):
            for seed in (1, 2, 77):
                spots = [self.pos(mood, None, NOW + i, seed=seed) for i in range(700)]
                self.assertGreaterEqual(min(spots), 0)
                self.assertLessEqual(max(spots), 60 - 13)
                self.assertGreater(max(spots) - min(spots), 15, (mood, seed))
                steps = [abs(a - b) for a, b in zip(spots, spots[1:])]
                self.assertEqual(max(steps), speed, (mood, seed))  # continuous, no jumps
                # it rests: at least one run of 3 equal positions
                self.assertTrue(any(a == b == c for a, b, c in
                                    zip(spots, spots[1:], spots[2:])), (mood, seed))

    def test_wander_is_continuous_across_stretches(self):
        for span in (1, 5, 47, 200):
            for speed in (1, 2, 4):
                length = sl.WANDER_REST + span
                for k in (0, 1, 7, 12345):
                    t = k * length
                    a = sl._wander(3, t - 1, span, speed)[0]
                    b = sl._wander(3, t, span, speed)[0]
                    self.assertLessEqual(abs(a - b), speed, (span, speed, k))
                    for i in (0, 1, length // 2, length - 1):
                        self.assertTrue(0 <= sl._wander(3, t + i, span, speed)[0] <= span)
        self.assertEqual(sl._wander(3, NOW, 0, 1), (0, True))

    def test_tick_s_samples_the_same_walk(self):
        # at 5 s a frame the creature takes the walk's steps once per 5 s
        for i in range(40):
            self.assertEqual(self.pos("calm", None, NOW * 5 + 5 * i + 3, tick_len=5),
                             self.pos("calm", None, NOW + i))

    def mid_rule(self):
        # a moment when a calm wander stands well away from the left end
        return next(NOW + j for j in range(2000) if self.pos("calm", None, NOW + j) >= 10)

    def test_parked_moods_walk_left_and_stop(self):
        for mood in ("needs", "idle", "asleep", "error"):
            since = self.mid_rule()
            walk = [self.pos(mood, since, since + i) for i in range(80)]
            self.assertGreater(walk[0], 0, mood)
            self.assertEqual(walk, sorted(walk, reverse=True), mood)
            self.assertTrue(all(a - b <= 1 for a, b in zip(walk, walk[1:])), mood)
            self.assertEqual(walk[-1], 0, mood)
            self.assertEqual(self.pos(mood, None, NOW), 0, mood)

    def test_yours_parks_30s_then_wanders(self):
        since = self.mid_rule()
        first = [self.pos("yours", since, since + d) for d in range(30)]
        self.assertEqual(first, sorted(first, reverse=True))
        later = {self.pos("yours", since, since + d) for d in range(40, 200)}
        self.assertGreater(len(later), 1)

    def test_red_holds_while_spinning_then_runs_at_4(self):
        since = self.mid_rule()
        spin = {self.pos("red", since, since + d) for d in range(20)}
        self.assertEqual(len(spin), 1)
        run = [self.pos("red", since, since + 20 + i) for i in range(400)]
        self.assertEqual(max(abs(a - b) for a, b in zip(run, run[1:])), 4)

    def test_short_span_does_not_crash(self):
        for cols in (13, 14, 17):
            p = sl.pose(1, "working", None, NOW, cols)
            self.assertTrue(0 <= p["pos"] <= max(cols - 13, 0))


def _cells(plain):
    """A plain string as terminal cells: a wide char is followed by ""."""
    out = []
    for ch in plain:
        out.append(ch)
        if sl.vwidth(ch) == 2:
            out.append("")
    return out


class CreatureCase(PresenceCase):
    """PresenceCase with the creature on (the suite default is off)."""

    def setUp(self):
        super().setUp()
        os.environ["RETRO_HUD_CREATURE"] = "tall"

    def tearDown(self):
        os.environ["RETRO_HUD_CREATURE"] = "0"
        for k in ("RETRO_HUD_CREATURE_SEED", "RETRO_HUD_CREATURE_COLOR", "RETRO_HUD_FRAME",
                  "RETRO_HUD_TICK_S"):
            os.environ.pop(k, None)
        super().tearDown()

    def rows(self, now=NOW, base=MINIMAL, cols=160, sid=None):
        return sl.render(self.payload(base, sid), cols, now)


class TestCreatureFrame(CreatureCase):
    ROW = sl.NEON_GREEN + "┌─" + sl.R + "x" * 20
    LOOK = {"seed": 11, "family": "alien", "color": 45}

    def test_box_sits_over_its_legs_and_the_frame_never_moves(self):
        for mood in MOODS_ALL:
            for bubble in ("", "ready", "y" * 18, "日本語のふきだし"):
                for icon in ("", "!"):
                    for cols in range(24, 241, 7):
                        for now in (NOW, NOW + 10, NOW + 170, NOW + 3333):
                            since = now - 7
                            pres = {"mood": mood, "bubble": bubble, "since": since,
                                    "mood_since": since, "icon": icon}
                            head, row1 = sl._frame_creature(self.ROW, cols, True, 50, now,
                                                            pres, self.LOOK)
                            label = (mood, bubble, cols, now)
                            bare = sl._frame(self.ROW, cols, "┐", True)
                            self.assertTrue(head.startswith(sl.R), label)
                            self.assertLessEqual(sl.vislen(head), cols, label)
                            self.assertEqual(sl.vislen(row1), cols, label)
                            p_row, p_bare = sl.strip_ansi(row1), sl.strip_ansi(bare)
                            self.assertEqual(p_row[:23], p_bare[:23], label)
                            self.assertTrue(p_row.endswith("┐"), label)
                            track = cols - sl.vislen(self.ROW) - 2
                            if track < 17:
                                self.assertEqual(head, sl.R, label)
                                self.assertEqual(row1, bare, label)
                                continue
                            p = sl.pose(11, mood, since, now, track, "alien", 45, icon)
                            h13, r13 = sl.render_box(p)
                            col = sl.vislen(self.ROW) + 1 + p["pos"]
                            hc, rc = _cells(sl.strip_ansi(head)), _cells(p_row)
                            self.assertEqual(hc[col:col + 13], _cells(sl.strip_ansi(h13)), label)
                            self.assertEqual(rc[col:col + 13], _cells(sl.strip_ansi(r13)), label)
                            self.assertNotIn(bubble[:2] or "\0", p_row, label)

    def test_bubble_on_the_head_line_beside_the_box(self):
        pres = {"mood": "yours", "bubble": "ready", "since": NOW, "mood_since": None}
        head, row1 = sl._frame_creature(self.ROW, 120, True, 50, NOW, pres, self.LOOK)
        self.assertRegex(sl.strip_ansi(head), r"[▀▄] +ready|ready +[▀▄]")
        self.assertNotIn("ready", sl.strip_ansi(row1))

    def test_alien_off_draws_nothing(self):
        pres = {"mood": "working", "bubble": "hi", "since": NOW, "mood_since": None}
        head, row1 = sl._frame_creature(self.ROW, 120, True, None, NOW, pres, self.LOOK)
        self.assertEqual(head, sl.R)
        self.assertEqual(row1, sl._frame(self.ROW, 120, "┐", True))
        head, row1 = sl._frame_creature(self.ROW, 120, False, 50, NOW, pres, self.LOOK)
        self.assertEqual((head, row1), (sl.R, self.ROW))

    def test_gauge_only_creature_follows_the_gauge(self):
        for pct, mood in ((10, "calm"), (75, "agitated"), (95, "red")):
            head, row1 = sl._frame_creature(self.ROW, 120, True, pct, NOW, None, self.LOOK)
            p = sl.pose(11, mood, None, NOW, 120 - sl.vislen(self.ROW) - 2, "alien", 45)
            self.assertIn(sl.render_box(p)[1], row1, pct)

    def test_the_box_is_one_agent_link(self):
        action = lambda name, text, extra="": sl.link("retro-hud://" + name, text)
        pres = {"mood": "working", "bubble": "ready", "since": NOW, "mood_since": None}
        head, row1 = sl._frame_creature(self.ROW, 120, True, 50, NOW, pres, self.LOOK, action)
        self.assertEqual(row1.count("retro-hud://card"), 1)
        self.assertEqual(head.count("retro-hud://card"), 1)
        plain_head = sl.strip_ansi(head)
        self.assertIn("ready", plain_head)
        self.assertNotIn("ready\a", head)  # the bubble is outside the link


class TestCreatureHud(CreatureCase):
    def test_three_lines_in_every_mode(self):
        for knobs in ({}, {"RETRO_HUD_ALIEN": "0"}, {"RETRO_HUD_FRAME": "0"},
                      {"RETRO_HUD_PRESENCE": "0"}):
            os.environ.update(knobs)
            try:
                for payload in (FULL, MINIMAL, OVERLOAD, {}):
                    for cols in range(50, 241, 10):
                        rows = sl.render(copy.deepcopy(payload), cols, NOW)
                        self.assertEqual(len(rows), 3, (knobs, cols))
                        self.assertTrue(rows[0].startswith(sl.R), (knobs, cols))
                        for row in rows:
                            self.assertLessEqual(sl.vislen(row), cols, (knobs, cols))
                        if knobs and "RETRO_HUD_PRESENCE" not in knobs:
                            self.assertEqual(rows[0], sl.R, (knobs, cols))
            finally:
                for k in knobs:
                    os.environ.pop(k, None)

    def test_off_is_the_two_row_hud(self):
        os.environ["RETRO_HUD_CREATURE"] = "0"
        rows = sl.render(copy.deepcopy(FULL), 160, NOW)
        self.assertEqual(len(rows), 2)
        self.assertIn(">o.o<", sl.strip_ansi(rows[0]))

    def test_rows_1_and_2_unchanged_by_the_creature(self):
        self.tx(user(NOW - 50), asst(NOW - 2, "tool_use"))
        self.events({"ts": NOW - 1, "text": "deploy finished", "ttl": 600})
        for alien in ("1", "0"):
            os.environ["RETRO_HUD_ALIEN"] = alien
            for cols in range(50, 241, 10):
                for t in (NOW, NOW + 10, NOW + 30):
                    on = sl.render(self.payload(FULL), cols, t)
                    os.environ["RETRO_HUD_CREATURE"] = "0"
                    off = sl.render(self.payload(FULL), cols, t)
                    os.environ["RETRO_HUD_CREATURE"] = "tall"
                    self.assertEqual(on[2], off[1], (alien, cols))
                    if alien == "0":
                        self.assertEqual(on[1:], off, cols)
                        self.assertEqual(on[0], sl.R, cols)
                        continue
                    p_on, p_off = sl.strip_ansi(on[1]), sl.strip_ansi(off[0])
                    self.assertEqual(sl.vislen(on[1]), sl.vislen(off[0]), cols)
                    # the creature's rule holds no spaces (the 2.x one may
                    # carry a bubble): its last space ends the segments
                    m = re.match(r"^(.*) [^ ]*┐$", p_on)
                    segs = m.group(1) if m else p_on
                    self.assertTrue(p_off.startswith(segs + (" " if m else "")), cols)
                    self.assertEqual(p_on[-1], p_off[-1])
        os.environ.pop("RETRO_HUD_ALIEN", None)

    def test_short_rule_hides_it_with_a_blank_head_line(self):
        rows = sl.render(copy.deepcopy(FULL), 60, NOW)
        self.assertEqual(rows[0], sl.R)
        self.assertFalse(re.search("[▀▄]", sl.strip_ansi(rows[1])))

    def test_mood_since_is_recorded_and_kept(self):
        self.tx(user(NOW - 9), asst(NOW - 2, "tool_use", ("tool_use",)))
        self.rows(NOW)
        s = self.state_file()
        self.assertEqual((s["mood"], s["mood_since"], s["creature"]), ("working", NOW, "alien"))
        self.rows(NOW + 10)
        self.assertEqual(self.state_file()["mood_since"], NOW)
        self.tx(user(NOW - 9), asst(NOW + 15))
        self.rows(NOW + 20)
        s = self.state_file()
        self.assertEqual((s["mood"], s["mood_since"]), ("yours", NOW + 20))

    def test_mood_since_drives_the_entry_tics(self):
        self.tx(user(NOW - 9), asst(NOW - 2, "tool_use", ("tool_use",)))
        first = self.rows(NOW)
        later = self.rows(NOW + 40)
        seed = sl.creature_seed(None, "", self.SID)
        segs = re.match(r"^(.*) [^ ]*┐$", sl.strip_ansi(later[1])).group(1)
        track = 160 - sl.vwidth(segs) - 2
        for now, rows in ((NOW, first), (NOW + 40, later)):
            p = sl.pose(seed, "working", NOW, now, track, "alien")
            self.assertIn(sl.render_box(p)[1], rows[1], now)
        # the first frame is the entry scatter, not the steady pose
        self.assertNotEqual(sl.render_box(sl.pose(seed, "working", None, NOW, track)),
                            sl.render_box(sl.pose(seed, "working", NOW, NOW, track)))

    def test_unwritable_cache_means_steady_poses(self):
        blocker = os.path.join(self.tmp, "file-not-dir")
        with open(blocker, "w") as f:
            f.write("x")
        os.environ["RETRO_HUD_CACHE_DIR"] = os.path.join(blocker, "sub")
        self.tx(asst(NOW - 2, "tool_use"))
        pres = sl.presence(self.payload(), NOW, 0, 0, 0, 0, creature=True)
        self.assertIsNone(pres["mood_since"])

    def test_seed_and_family_overrides(self):
        self.tx(asst(NOW - 2, "tool_use"))
        base = self.rows(NOW + 100)
        os.environ["RETRO_HUD_CREATURE_SEED"] = "7"
        env7 = self.rows(NOW + 100)
        self.assertNotEqual(env7[0], base[0])
        os.environ.pop("RETRO_HUD_CREATURE_SEED")
        self.put_state(seed=7)
        self.assertEqual(self.rows(NOW + 100)[:2], env7[:2])
        self.put_state(seed=True)          # junk: ignored
        self.assertEqual(self.rows(NOW + 100)[0], base[0])
        os.environ["RETRO_HUD_SPRITE"] = "robot"
        self.rows(NOW + 100)
        self.assertEqual(self.state_file()["creature"], "robot")
        self.put_state(sprite="ghost")
        self.rows(NOW + 100)
        self.assertEqual(self.state_file()["creature"], "blob")
        self.put_state(sprite="beast")
        self.rows(NOW + 100)
        self.assertEqual(self.state_file()["creature"], "beast")

    def test_color_pin(self):
        self.tx(asst(NOW - 2, "tool_use"))
        os.environ["RETRO_HUD_CREATURE_COLOR"] = "pink"
        self.assertTrue(_has_color(self.rows(NOW + 100)[0], 198))

    def test_mood_colour_follows_the_session(self):
        os.environ["RETRO_HUD_CREATURE_COLOR"] = "mood"
        os.environ["RETRO_HUD_CREATURE_SEED"] = "3"
        self.tx(user(NOW - 50), asst(NOW - 2, "tool_use"))      # working: the seed's colour
        self.assertTrue(_has_color(self.rows(NOW)[0], sl.creature_color(3)))
        self.hooks({"ts": NOW - 1, "state": "needs"})          # needs you: yellow
        self.assertTrue(_has_color(self.rows(NOW)[0], 226))
        os.environ["RETRO_HUD_CREATURE_COLOR"] = "pink"
        self.assertTrue(_has_color(self.rows(NOW)[0], 198))

    def test_family_names_in_the_state_file_are_ignored_when_off(self):
        self.tx(asst(NOW - 2, "tool_use"))
        os.environ["RETRO_HUD_CREATURE"] = "0"
        os.environ["RETRO_HUD_SPRITE"] = "cat"
        self.put_state(sprite="blob")
        self.assertIn("=^.^/", self.row1(NOW))
        self.assertNotIn("creature", self.state_file())

    def test_gauge_only_creature_peeks_at_the_state_file(self):
        # no transcript: unknown state, the gauge-only creature; the
        # state file's seed still applies and nothing is written
        self.put_state(seed=7)
        before = open(self.path(".state.json")).read()
        a = self.rows(NOW, FULL)
        os.environ["RETRO_HUD_CREATURE_SEED"] = "7"
        self.put_state()
        self.assertEqual(self.rows(NOW, FULL), a)
        self.put_state(seed=7)
        self.rows(NOW, FULL)
        self.assertEqual(open(self.path(".state.json")).read(), before)

    def test_icon_events(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.events({"ts": NOW, "icon": "!", "ttl": 30})
        head = sl.strip_ansi(self.rows(NOW + 1)[0])
        self.assertIn("!", head)
        self.assertNotIn("!", sl.strip_ansi(self.rows(NOW + 40)[0]))
        self.events({"ts": NOW + 50, "text": "built", "icon": "*", "ttl": 30})
        head = sl.strip_ansi(self.rows(NOW + 51)[0])
        self.assertIn("*", head)
        self.assertIn("built", head)

    def test_bad_icons_are_ignored(self):
        evs = [{"ts": NOW, "icon": bad, "ttl": 30}
               for bad in ("ab", "́", "", " ", "\x1b", 5, None, "❤️")]
        self.assertEqual(sl.newest_icon(evs, NOW), "")
        self.assertEqual(sl.newest_icon([{"ts": NOW, "icon": "⚑", "ttl": 30}], NOW),
                         "⚑")
        self.assertEqual(sl.newest_icon([{"ts": NOW - 40, "icon": "!"}], NOW), "")

    def test_wave_event_raises_the_arms(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.events({"ts": NOW, "text": "wave", "ttl": 30})
        for el in (1, 4, 7):
            pres = sl.presence(self.payload(), NOW + el, 0, 0, 0, 0, creature=True)
            self.assertEqual(pres["mood"], "yours")
            # a gesture is not a mood change: clean arms up, no scatter, no jump
            cv = sl.pose(3, "yours", pres["mood_since"], NOW + el, 60)["canvas"]
            steady = sl.pose(3, "yours", None, NOW + el, 60)["canvas"]
            self.assertEqual(cv, steady, el)
        self.assertEqual(self.state_file()["mood"], "working")  # the gesture is not stored


class TestCreatureSize(PresenceCase):
    """RETRO_HUD_CREATURE picks tiny (default), big, tall or 0; the state
    file's `size` overrides it unless the creature is off."""

    def tearDown(self):
        os.environ["RETRO_HUD_CREATURE"] = "0"
        os.environ.pop("RETRO_HUD_TICK_S", None)
        super().tearDown()

    def size(self, env, **state):
        if env is None:
            os.environ.pop("RETRO_HUD_CREATURE", None)
        else:
            os.environ["RETRO_HUD_CREATURE"] = env
        if state:
            self.put_state(**state)
        return sl.creature_size(self.payload())

    def test_env_values(self):
        for env, want in ((None, "tiny"), ("", "tiny"), ("1", "tiny"), ("tiny", "tiny"),
                          ("big", "big"), ("tall", "tall"), ("BIG", "big"), ("0", "off"),
                          ("huge", "tiny")):
            self.assertEqual(self.size(env), want, env)

    def test_state_file_size_overrides_but_never_turns_it_on(self):
        self.assertEqual(self.size("tiny", size="big"), "big")
        self.assertEqual(self.size("big", size="tall"), "tall")
        self.assertEqual(self.size("tall", size="tiny"), "tiny")
        self.assertEqual(self.size("tiny", size="huge"), "tiny")   # junk: ignored
        self.assertEqual(self.size("big", size=3), "big")
        self.assertEqual(self.size("0", size="big"), "off")         # off is off
        os.environ["RETRO_HUD_CREATURE"] = "big"
        self.assertEqual(sl.creature_size({}), "big")               # no session: env only

    def test_tick_s(self):
        for env, want in ((None, 1), ("5", 5), ("1", 1), ("0", 1), ("-3", 1), ("x", 1),
                          ("1.5", 1), ("", 1), (" 2 ", 2)):
            if env is None:
                os.environ.pop("RETRO_HUD_TICK_S", None)
            else:
                os.environ["RETRO_HUD_TICK_S"] = env
            self.assertEqual(sl.tick_s(), want, env)

    def test_line_counts_per_size(self):
        self.tx(user(NOW - 50), asst(NOW - 2, "tool_use"))
        for env, n in (("tiny", 2), ("big", 2), ("tall", 3), ("0", 2), (None, 2)):
            if env is None:
                os.environ.pop("RETRO_HUD_CREATURE", None)
            else:
                os.environ["RETRO_HUD_CREATURE"] = env
            for payload in (FULL, MINIMAL, OVERLOAD, {}):
                for cols in range(50, 241, 30):
                    rows = sl.render(self.payload(payload), cols, NOW)
                    self.assertEqual(len(rows), n, (env, cols))
                    for row in rows:
                        self.assertLessEqual(sl.vislen(row), cols, (env, cols))
        os.environ["RETRO_HUD_CREATURE"] = "tiny"
        self.put_state(size="tall")
        self.assertEqual(len(sl.render(self.payload(FULL), 160, NOW)), 3)

    def test_degraded_fallback_line_counts(self):
        import contextlib
        import io
        saved = sl.render
        sl.render = lambda *a: 1 / 0
        try:
            for env, n in (("tiny", 2), ("big", 2), ("tall", 3), ("0", 2)):
                os.environ["RETRO_HUD_CREATURE"] = env
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    sl.main(["--demo"])
                self.assertEqual(len(buf.getvalue().split("\n")), n, env)
        finally:
            sl.render = saved


_TINY_CELL_RE = re.compile(r"(?:(?:\x1b\[[0-9;]*m)*[^\x1b]\x1b\[0m)*")
_QUIET = {"blink": False, "hop": False, "breathe": False}


def _dots(cv):
    return sum(1 for row in cv for v in row if v and v != "e")


class TestTinyPose(unittest.TestCase):
    """The braille creature: a fixed 7-cell box, half-cell steps, and every
    behaviour reachable from (seed, tick)."""

    def tp(self, mood, t=NOW, seed=4, fam="alien", since=None, **kw):
        return sl.tiny_pose(seed, mood, since, t, 60, fam, **kw)

    def quiet(self):
        saved = sl.alive_flags
        sl.alive_flags = lambda s, t: dict(_QUIET)
        self.addCleanup(setattr, sl, "alive_flags", saved)

    def test_box_is_7_cells_for_every_pose(self):
        for fam in sl.FAMILIES:
            for seed in range(0, 30, 7):
                for mood in MOODS_ALL:
                    for el in (None, 0, 3, 7, 12, 40, 4000):
                        for t in range(NOW, NOW + 8):
                            for icon in ("", "!", "\U0001F6A9"):
                                since = None if el is None else t - el
                                p = sl.tiny_pose(seed, mood, since, t, 60, fam, icon=icon)
                                box = sl.render_tiny(p)
                                label = (fam, seed, mood, el, t, icon)
                                self.assertEqual(sl.vislen(box), 7, label)
                                self.assertTrue(_TINY_CELL_RE.fullmatch(box), label)
                                self.assertEqual([len(r) for r in p["dots"]], [14] * 4, label)
                                self.assertIn(p["sub"], (0, 1), label)
                                self.assertTrue(0 <= p["pos"] <= 60 - 7, label)

    def test_nothing_falls_off_the_box(self):
        # the widest moves (breath, shake, jitter, legs, waving arms) at
        # either half-cell offset keep every dot inside the 14 columns
        saved = sl.alive_flags
        sl.alive_flags = lambda s, t: {"blink": False, "hop": False, "breathe": True}
        try:
            for fam in sl.FAMILIES:
                for seed in range(12):
                    body = _dots(sl._breathe(sl._tiny_body(seed, fam), 5))
                    for mood in ("calm", "working", "error", "red", "agitated"):
                        if mood == "agitated" or (fam == "alien" and mood == "red"):
                            continue  # arms or wide eyes change the count: own tests
                        for t in range(NOW, NOW + 12):
                            p = sl.tiny_pose(seed, mood, None, t, 60, fam)
                            self.assertEqual(_dots(p["dots"]), body, (fam, seed, mood, t))
        finally:
            sl.alive_flags = saved

    def test_half_cell_steps(self):
        self.quiet()
        dots = [self.tp("calm", NOW + i) for i in range(400)]
        at = [2 * p["pos"] + p["sub"] for p in dots]
        self.assertEqual(max(abs(a - b) for a, b in zip(at, at[1:])), 1)
        self.assertEqual({p["sub"] for p in dots}, {0, 1})
        for p in dots:
            first = min(c for row in p["dots"] for c, v in enumerate(row) if v)
            self.assertEqual(first, 1 + p["sub"])        # offset 1 = one dot right
            base = sl._tiny_body(4, "alien")
            self.assertEqual(p["dots"], sl._shift(base, p["sub"]))

    def test_deterministic(self):
        for mood in MOODS_ALL:
            for t in (NOW, NOW + 3, NOW + 999):
                self.assertEqual(self.tp(mood, t, since=t - 4), self.tp(mood, t, since=t - 4))

    def test_tick_s_holds_the_frame(self):
        for i in range(5):
            self.assertEqual(self.tp("working", NOW * 5 + i, tick_len=5),
                             self.tp("working", NOW, tick_len=1))

    def test_alien_is_the_old_guy(self):
        # seed-independent: two 2x2 eye holes a dot apart under a head row,
        # arms at the top corners, green; o.o / -.- / >o.o< / \o.o/
        self.quiet()
        looks = set()
        for s in range(50):
            p = self.tp("calm", NOW, seed=s)
            looks.add(str(sl._shift(p["dots"], -p["sub"])))
        self.assertEqual(len(looks), 1)
        p = self.tp("calm", NOW, seed=0)
        cv = sl._shift(p["dots"], -p["sub"])  # body from dot column 1
        x0 = 1
        for r in (1, 2):
            self.assertEqual([cv[r][x0 + c] for c in (2, 3, 5, 6)], ["e"] * 4)  # the o's
            self.assertEqual(cv[r][x0 + 4], "b")                                # the .
            self.assertEqual((cv[r][x0 + 1], cv[r][x0 + 7]), ("b", "b"))
        self.assertTrue(all(cv[0][x0 + c] == "b" for c in (2, 3, 4, 5, 6)))      # head
        self.assertEqual((cv[0][x0], cv[0][x0 + 8]), ("b", "b"))                 # arms out
        self.assertEqual((cv[0][x0 + 1], cv[0][x0 + 7]), (None, None))
        self.assertEqual(p["body"], 46)
        cells = sl.braille(p["dots"])
        self.assertEqual(sum(1 for c in cells if c), 5)                          # 5 cells wide

    def test_alien_moods_keep_the_old_vocabulary(self):
        self.quiet()
        p = self.tp("agitated", NOW)
        cv = sl._shift(p["dots"], -p["sub"])
        self.assertEqual((cv[0][1], cv[0][9]), (None, None))         # >o.o<: in and down
        self.assertEqual((cv[3][1], cv[3][9]), ("b", "b"))
        self.assertEqual(p["body"], sl.AMBER)
        red = self.tp("red", NOW)
        self.assertEqual(red["body"], sl.RED_256)
        cols = sorted({c for c in range(14) for r in (0, 1) if red["dots"][r][c]})
        lo, hi = cols[0], cols[-1]
        self.assertEqual((red["dots"][1][lo], red["dots"][1][hi]), ("b", "b"))  # \o.o/: up
        self.assertEqual(self.tp("calm", NOW)["body"], 46)
        self.assertEqual(self.tp("calm", NOW, color=198)["body"], 198)          # a pin wins

    def test_blink_is_a_slit_and_breath_is_a_dot_wider(self):
        t = _tick_with(4, blink=True)
        cv = self.tp("calm", t)["dots"]
        holes = [(r, c) for r in range(4) for c in range(14) if cv[r][c] == "e"]
        self.assertEqual(sorted({r for r, _ in holes}), [2])  # -.- : a one-dot slit
        self.assertEqual(len(holes), 4)
        g = self.tp("calm", t, fam="beast")["dots"]
        self.assertFalse(any(v == "e" for row in g for v in row))  # generated: eyes fill
        q, b = _tick_with(4), _tick_with(4, breathe=True)
        self.assertEqual(_width(self.tp("calm", b)["dots"]), _width(self.tp("calm", q)["dots"]) + 1)

    def test_hop_rises_a_dot_row_while_calm_or_working(self):
        t = _tick_with(4, hop=True)
        for mood in ("calm", "working"):
            self.assertFalse(any(self.tp(mood, t)["dots"][3]), mood)
        for mood in ("idle", "error", "agitated"):
            self.assertTrue(any(self.tp(mood, t)["dots"][3]), mood)

    def test_yours_stops_and_waves(self):
        self.quiet()
        a, b = self.tp("yours", NOW), self.tp("yours", NOW + 1)
        self.assertNotEqual(a["dots"], b["dots"])            # the arms go up and down
        self.assertFalse(a["right"])
        since = NOW - 100
        walk = [self.tp("yours", since + i, since=since)["pos"] for i in range(30)]
        self.assertEqual(walk, sorted(walk, reverse=True))  # parked: never walks right
        for fam in ("beast", "bot", "blob"):
            up = self.tp("yours", NOW, fam=fam)["dots"]
            calm = self.tp("calm", NOW, fam=fam)["dots"]
            self.assertEqual(_dots(up), _dots(calm) + 2, fam)  # two arm dots

    def test_needs_bounces_with_a_yellow_question_mark(self):
        self.quiet()
        for fam in sl.FAMILIES:
            even, odd = self.tp("needs", NOW, fam=fam), self.tp("needs", NOW + 1, fam=fam)
            self.assertTrue(any(even["dots"][3]))
            self.assertFalse(any(odd["dots"][3]))
            for p in (even, odd):
                box = sl.render_tiny(p)
                cells = sl.braille(p["dots"])
                self.assertIsNone(cells[p["ask"]], fam)        # beside it, not on it
                self.assertIn("?", sl.strip_ansi(box))
                self.assertTrue(_has_color(box, 226))

    def test_idle_blinks_slowly_and_asleep_lies_flat(self):
        self.quiet()
        shut = [sum(v == "e" for row in self.tp("idle", NOW + i)["dots"] for v in row) < 8
                for i in range(6)]
        self.assertEqual(sum(shut), 2)
        for fam in sl.FAMILIES:
            for t in range(NOW, NOW + 30):
                p = self.tp("asleep", t, fam=fam)
                self.assertFalse(any(p["dots"][0]) or any(p["dots"][1]), (fam, t))
                self.assertFalse(any(v == "e" for row in p["dots"] for v in row))
        sl.alive_flags = TestTinyPose._real_flags
        for t in range(NOW, NOW + 60):  # blinks and hops never wake it
            p = self.tp("asleep", t)
            self.assertFalse(any(p["dots"][0]) or any(p["dots"][1]), t)

    def test_error_shakes_and_red_jitters(self):
        self.quiet()
        a, b = self.tp("error", NOW), self.tp("error", NOW + 1)
        self.assertEqual(a["pos"], b["pos"])
        self.assertIn(b["dots"], (sl._shift(a["dots"], 2), sl._shift(a["dots"], -2)))
        firsts = {min(c for row in self.tp("red", NOW + i)["dots"] for c, v in enumerate(row) if v)
                  - self.tp("red", NOW + i)["sub"] for i in range(40)}
        self.assertGreater(len(firsts), 1)

    def test_scatter_on_mood_change(self):
        self.quiet()
        steady = self.tp("working", NOW)["dots"]
        a = self.tp("working", NOW, since=NOW - 1)["dots"]
        self.assertNotEqual(a, steady)
        self.assertEqual(_dots(a), _dots(steady))
        self.assertEqual(self.tp("working", NOW, since=NOW - 11)["dots"], steady)


TestTinyPose._real_flags = sl.alive_flags


class TestRobotPose(unittest.TestCase):
    """The robot at big and tall: 8 dot rows in a fixed 9-cell box, half-cell
    steps, and every mood reachable from (seed, tick)."""

    def rp(self, mood, t=NOW, seed=4, since=None, **kw):
        return sl.robot_pose(seed, mood, since, t, 60, **kw)

    def quiet(self, **flags):
        saved = sl.alive_flags
        on = dict(_QUIET, **flags)
        sl.alive_flags = lambda s, t: dict(on)
        self.addCleanup(setattr, sl, "alive_flags", saved)

    def base(self, seed=4):
        return sl._robot_body(seed)

    def test_box_is_9_cells_on_both_lines_for_every_pose(self):
        for seed in range(0, 30, 7):
            for mood in MOODS_ALL:
                for el in (None, 0, 3, 7, 12, 40, 4000):
                    for t in range(NOW, NOW + 8):
                        for icon in ("", "!", "\U0001F6A9"):
                            since = None if el is None else t - el
                            p = sl.robot_pose(seed, mood, since, t, 60, icon=icon)
                            label = (seed, mood, el, t, icon)
                            self.assertEqual(p["kind"], "robot", label)
                            self.assertEqual(p["w"], sl.ROBOT_W, label)
                            self.assertEqual([len(r) for r in p["dots"]], [2 * sl.ROBOT_W] * 8, label)
                            self.assertIn(p["sub"], (0, 1), label)
                            self.assertTrue(0 <= p["pos"] <= 60 - sl.ROBOT_W, label)
                            for rule_top in (False, True):
                                up, low = sl.render_robot(p, rule_top)
                                self.assertEqual(sl.vislen(up), sl.ROBOT_W, label)
                                self.assertEqual(sl.vislen(low), sl.ROBOT_W, label)
                                self.assertTrue(_CELL_RE.fullmatch(up), label)
                                self.assertTrue(_CELL_RE.fullmatch(low), label)

    def test_steady_calm_dots_are_the_grid(self):
        self.quiet()
        g = sl.robot_grid(4)
        for t in range(NOW, NOW + 40):
            p = self.rp("calm", t)
            cv = sl._shift(p["dots"], -p["sub"])
            for r in range(8):
                self.assertEqual(cv[r][:3] + cv[r][15:], [None] * 6, (t, r))
                self.assertEqual(cv[r][3:15], [{"body": "b", "eye": "e", "hole": "h"}.get(v)
                                               for v in g[r]], (t, r))

    def test_nothing_falls_off_the_box(self):
        self.quiet(breathe=True)
        for seed in range(12):
            body = _dots(sl._breathe(self.base(seed), 8))
            for mood in ("calm", "working", "error", "red"):
                for t in range(NOW, NOW + 12):
                    p = sl.robot_pose(seed, mood, None, t, 60)
                    self.assertEqual(_dots(p["dots"]), body, (seed, mood, t))

    def test_half_cell_steps(self):
        self.quiet()
        ps = [self.rp("calm", NOW + i) for i in range(400)]
        at = [2 * p["pos"] + p["sub"] for p in ps]
        self.assertEqual(max(abs(a - b) for a, b in zip(at, at[1:])), 1)
        self.assertEqual({p["sub"] for p in ps}, {0, 1})
        for p in ps:
            self.assertEqual(p["dots"], sl._shift(self.base(), p["sub"]))

    def test_render_cells(self):
        self.quiet()
        p = self.rp("calm", color=46)
        up, low = sl.render_robot(p)
        cv = p["dots"]
        for line, rows, blank in ((up, cv[:4], " "), (low, cv[4:], "─")):
            plain = sl.strip_ansi(line)
            for c, (ch, want) in enumerate(zip(plain, sl.braille(rows))):
                self.assertEqual(ch, want or blank, (c, line))
        self.assertEqual(sl.strip_ansi(sl.render_robot(p, rule_top=True)[0]).replace("─", " "),
                         sl.strip_ansi(up))
        self.assertTrue(_has_color(up + low, 46))
        self.assertFalse(_has_color(up + low, 255))  # no white: eyes are holes

    def test_blink_fills_the_eyes_but_not_the_chest(self):
        self.quiet(blink=True)
        seed = next(s for s in range(50) if sl.robot_parts(s)["chest"] != "plain")
        cv = sl.robot_pose(seed, "calm", None, NOW, 60)["dots"]
        self.assertFalse(any(v == "e" for row in cv for v in row))
        self.assertTrue(any(v == "h" for row in cv for v in row))
        eyes = sum(1 for row in self.base(seed) for v in row if v == "e")
        self.assertEqual(_dots(cv), _dots(self.base(seed)) + eyes)

    def test_breath_hop_and_walk(self):
        self.quiet(breathe=True)
        self.assertEqual(self.rp("calm")["dots"], sl._shift(sl._breathe(self.base(), 8),
                                                            self.rp("calm")["sub"]))
        self.quiet(hop=True)
        for mood in ("calm", "working"):
            p = self.rp(mood, NOW + 2)  # an even tick: no walk step
            self.assertEqual(p["dots"], sl._shift(sl._rise(self.base()), p["sub"]), mood)
        self.assertFalse(any(self.rp("calm", NOW + 2)["dots"][7]))
        self.quiet()
        odd = next(t for t in range(NOW, NOW + 4) if t % 2)
        p = self.rp("working", odd)
        cv = sl._shift(p["dots"], -p["sub"])
        self.assertEqual(cv[:6], self.base()[:6])
        self.assertNotEqual(cv[6:], self.base()[6:])    # the legs step
        self.assertEqual(_dots(cv), _dots(self.base()))

    def test_yours_waves_and_jumps_once(self):
        self.quiet()
        seen = set()
        for t in range(NOW, NOW + 4):
            p = self.rp("yours", t, since=t - 40)
            cv = sl._shift(p["dots"], -p["sub"])
            extra = _dots(cv) - _dots(self.base())
            self.assertEqual(extra, 2, t)                  # two arm tips beside the head
            seen |= {r for r in range(8) if cv[r] != self.base()[r]}
        self.assertEqual(seen, {1, 2})                     # up and down
        jump = self.rp("yours", NOW, since=NOW - 1)["dots"]
        self.assertFalse(any(jump[7]))                     # risen a dot row

    def test_needs_bounces_with_a_yellow_question_mark(self):
        self.quiet()
        ps = [self.rp("needs", NOW + i, since=NOW - 60) for i in range(4)]
        self.assertTrue(all(p["ask"] is not None for p in ps))
        self.assertEqual({any(p["dots"][7]) for p in ps}, {True, False})  # bounces
        up, low = sl.render_robot(ps[0])
        self.assertIn("?", sl.strip_ansi(up))
        self.assertNotIn("?", sl.strip_ansi(low))
        self.assertTrue(_has_color(up, sl.ICON_256))

    def test_idle_blinks_slowly_and_asleep_powers_down(self):
        self.quiet()
        shut = [not any(v == "e" for row in self.rp("idle", NOW + i)["dots"] for v in row)
                for i in range(12)]
        self.assertEqual(sum(shut), 4)
        p = self.rp("asleep")
        self.assertEqual(p["dots"][:4], [[None] * 18] * 4)   # the upper text row empties
        self.assertTrue(all(any(row) for row in p["dots"][4:]))
        self.assertFalse(any(v == "e" for row in p["dots"] for v in row))
        self.assertEqual(p["icon_row"], 1)
        up, low = sl.render_robot(sl.robot_pose(4, "asleep", None, NOW, 60, icon="z"))
        self.assertEqual(sl.strip_ansi(up).strip(), "")
        self.assertIn("z", sl.strip_ansi(low))

    def test_error_shakes_red_jitters_agitated_widens_the_eyes(self):
        self.quiet()
        for mood in ("error", "red"):
            at = {tuple(map(tuple, sl._shift(self.rp(mood, NOW + i)["dots"], -self.rp(mood, NOW + i)["sub"])))
                  for i in range(12)}
            self.assertGreater(len(at), 1, mood)
        self.assertEqual(self.rp("red")["body"], sl.RED_256)
        p = self.rp("agitated")
        self.assertEqual(p["body"], sl.AMBER)
        cv = sl._shift(p["dots"], -p["sub"])
        eyes = [c for c in range(18) if cv[2][c] == "e"]
        self.assertTrue(all(cv[1][c] == "e" for c in eyes))     # wide eyes: a row taller

    def test_scatter_on_mood_change(self):
        self.quiet()
        t = next(t for t in range(NOW, NOW + 9) if self.rp("working", t)["sub"] == 0)
        cv = self.rp("working", t, since=t - 1)["dots"]
        self.assertNotEqual(cv, self.base())
        self.assertEqual(_dots(cv), _dots(self.base()))

    def test_deterministic_and_tick_s(self):
        for mood in MOODS_ALL:
            for t in (NOW, NOW + 3, NOW + 999):
                self.assertEqual(self.rp(mood, t, since=t - 4), self.rp(mood, t, since=t - 4))
        for i in range(5):
            self.assertEqual(self.rp("working", NOW * 5 + i, tick_len=5),
                             self.rp("working", NOW, tick_len=1))

    def test_big_pose_dispatches_by_family(self):
        for fam in sl.FAMILIES:
            p = sl.big_pose(3, "calm", None, NOW, 60, fam)
            self.assertEqual(p["kind"], "robot" if fam == "robot" else "half", fam)
            self.assertEqual(p["w"], sl.ROBOT_W if fam == "robot" else sl.BOX_W, fam)
            up, low = sl.render_big(p, rule_top=True)
            self.assertEqual((sl.vislen(up), sl.vislen(low)), (p["w"], p["w"]), fam)
        self.assertEqual(sl.big_pose(3, "calm", None, NOW, 60, "robot"),
                         sl.robot_pose(3, "calm", None, NOW, 60))


class TestTinyFrame(CreatureCase):
    ROW = sl.NEON_GREEN + "┌─" + sl.R + "x" * 20
    LOOK = {"seed": 11, "family": "alien", "color": None}

    def test_box_on_the_rule_and_the_frame_never_moves(self):
        for mood in MOODS_ALL:
            for bubble in ("", "ready", "y" * 18, "日本語のふきだし"):
                for cols in range(24, 200, 9):
                    for now in (NOW, NOW + 1, NOW + 170):
                        pres = {"mood": mood, "bubble": bubble, "since": now - 7,
                                "mood_since": now - 7, "icon": ""}
                        row1 = sl._frame_tiny(self.ROW, cols, True, 50, now, pres, self.LOOK)
                        bare = sl._frame(self.ROW, cols, "┐", True)
                        label = (mood, bubble, cols, now)
                        self.assertEqual(sl.vislen(row1), cols, label)
                        p_row = sl.strip_ansi(row1)
                        self.assertEqual(p_row[:23], sl.strip_ansi(bare)[:23], label)
                        self.assertTrue(p_row.endswith("┐"), label)
                        track = cols - sl.vislen(self.ROW) - 2
                        if track < 11:
                            self.assertEqual(row1, bare, label)
                            continue
                        p = sl.tiny_pose(11, mood, now - 7, now, track, "alien")
                        col = sl.vislen(self.ROW) + 1 + p["pos"]
                        self.assertEqual(_cells(p_row)[col:col + 7],
                                         _cells(sl.strip_ansi(sl.render_tiny(p))), label)

    def test_bubble_beside_it_on_the_rule(self):
        pres = {"mood": "yours", "bubble": "ready", "since": NOW, "mood_since": None}
        row1 = sl._frame_tiny(self.ROW, 120, True, 50, NOW, pres, self.LOOK)
        self.assertRegex(sl.strip_ansi(row1), r"[⠁-⣿]─*╴ready|ready╶─*[⠁-⣿]")

    def test_the_box_is_one_agent_link(self):
        action = lambda name, text, extra="": sl.link("retro-hud://" + name, text)
        pres = {"mood": "working", "bubble": "ready", "since": NOW, "mood_since": None}
        row1 = sl._frame_tiny(self.ROW, 120, True, 50, NOW, pres, self.LOOK, action)
        self.assertEqual(row1.count("retro-hud://card"), 1)
        self.assertNotIn("ready\a", row1)

    def test_hud_tiny_two_lines_rows_unchanged(self):
        os.environ["RETRO_HUD_CREATURE"] = "tiny"
        self.tx(user(NOW - 50), asst(NOW - 2, "tool_use"))
        for cols in range(50, 241, 10):
            for t in (NOW, NOW + 1, NOW + 30):
                on = sl.render(self.payload(FULL), cols, t)
                os.environ["RETRO_HUD_CREATURE"] = "0"
                off = sl.render(self.payload(FULL), cols, t)
                os.environ["RETRO_HUD_CREATURE"] = "tiny"
                self.assertEqual(len(on), 2)
                self.assertEqual(on[1], off[1], cols)
                self.assertEqual(sl.vislen(on[0]), sl.vislen(off[0]), cols)
                self.assertEqual(sl.strip_ansi(on[0])[-1], "┐")

    def test_tick_s_is_honoured(self):
        os.environ["RETRO_HUD_CREATURE"] = "tiny"
        self.tx(user(NOW - 50), asst(NOW - 2, "tool_use"))
        start = NOW - NOW % 5
        one = [sl.render(self.payload(FULL), 200, start + i)[0] for i in range(5)]
        self.assertGreater(len(set(one)), 1)            # a new frame every second
        os.environ["RETRO_HUD_TICK_S"] = "5"
        five = [sl.render(self.payload(FULL), 200, start + i)[0] for i in range(5)]
        self.assertEqual(len(set(five)), 1)              # one frame per 5 s


class TestBigFrame(CreatureCase):
    """big: the half-block creature straddles rows 1 and 2, no head line."""
    ROW1 = sl.NEON_GREEN + "┌─" + sl.R + "x" * 20
    LOOK = {"seed": 11, "family": "alien", "color": None}

    def test_box_straddles_the_rows_and_nothing_else_moves(self):
        for n2 in (10, 30):
            row2 = sl.NEON_GREEN + "└─" + sl.R + "y" * n2
            for mood in MOODS_ALL:
                for bubble in ("", "ready", "日本語のふきだし"):
                    for icon in ("", "!"):
                        for cols in range(41, 200, 11):
                            for now in (NOW, NOW + 1, NOW + 170):
                                pres = {"mood": mood, "bubble": bubble, "since": now - 7,
                                        "mood_since": now - 7, "icon": icon}
                                r1, r2 = sl._frame_big(self.ROW1, row2, cols, True, 50, now,
                                                       pres, self.LOOK)
                                b1 = sl._frame(self.ROW1, cols, "┐", True)
                                b2 = sl._frame(row2, cols, "┘", True)
                                label = (n2, mood, bubble, cols, now)
                                self.assertEqual(sl.vislen(r1), cols, label)
                                self.assertEqual(sl.vislen(r2), cols, label)
                                start = max(sl.vislen(self.ROW1), sl.vislen(row2)) + 1
                                track = cols - 1 - start
                                if track < 17:
                                    self.assertEqual((r1, r2), (b1, b2), label)
                                    continue
                                p = sl.pose(11, mood, now - 7, now, track, "alien", None, icon)
                                top, bottom = sl.render_box(p, rule_top=True)
                                col = start + p["pos"]
                                c1, c2 = _cells(sl.strip_ansi(r1)), _cells(sl.strip_ansi(r2))
                                k1, k2 = _cells(sl.strip_ansi(b1)), _cells(sl.strip_ansi(b2))
                                self.assertEqual(c1[col:col + 13], _cells(sl.strip_ansi(top)), label)
                                self.assertEqual(c2[col:col + 13], _cells(sl.strip_ansi(bottom)),
                                                 label)
                                # row 2 outside the box is the bare row, byte for byte
                                self.assertEqual(c2[:col] + c2[col + 13:], k2[:col] + k2[col + 13:],
                                                 label)
                                r0 = sl.vislen(self.ROW1) + 1  # row 1 up to its rule
                                self.assertEqual(c1[:r0], k1[:r0], label)
                                self.assertEqual((c1[-1], c2[-1]), ("┐", "┘"), label)
                                if bubble:
                                    self.assertNotIn(bubble[:2], sl.strip_ansi(r2), label)

    def test_bubble_on_row_1_beside_the_head(self):
        row2 = sl.NEON_GREEN + "└─" + sl.R + "y" * 10
        pres = {"mood": "yours", "bubble": "ready", "since": NOW, "mood_since": None}
        r1, r2 = sl._frame_big(self.ROW1, row2, 120, True, 50, NOW, pres, self.LOOK)
        self.assertIn("ready", sl.strip_ansi(r1))
        self.assertNotIn("ready", sl.strip_ansi(r2))

    def test_short_shared_rule_hides_it(self):
        row2 = sl.NEON_GREEN + "└─" + sl.R + "y" * 101
        r1, r2 = sl._frame_big(self.ROW1, row2, 120, True, 50, NOW, None, self.LOOK)
        self.assertEqual(r1, sl._frame(self.ROW1, 120, "┐", True))
        self.assertEqual(r2, sl._frame(row2, 120, "┘", True))

    def test_the_box_is_linked_on_both_rows(self):
        action = lambda name, text, extra="": sl.link("retro-hud://" + name, text)
        row2 = sl.NEON_GREEN + "└─" + sl.R + "y" * 10
        pres = {"mood": "working", "bubble": "ready", "since": NOW, "mood_since": None}
        r1, r2 = sl._frame_big(self.ROW1, row2, 120, True, 50, NOW, pres, self.LOOK, action)
        self.assertEqual((r1.count("retro-hud://card"), r2.count("retro-hud://card")), (1, 1))
        self.assertNotIn("ready\a", r1)

    def test_hud_big_is_two_lines_and_row_2_keeps_its_segments(self):
        os.environ["RETRO_HUD_CREATURE"] = "big"
        self.tx(user(NOW - 50), asst(NOW - 2, "tool_use"))
        seen = False
        for cols in range(50, 241, 10):
            for t in (NOW, NOW + 1, NOW + 30):
                on = sl.render(self.payload(FULL), cols, t)
                os.environ["RETRO_HUD_CREATURE"] = "0"
                off = sl.render(self.payload(FULL), cols, t)
                os.environ["RETRO_HUD_CREATURE"] = "big"
                self.assertEqual(len(on), 2)
                for a, b in zip(on, off):
                    self.assertEqual(sl.vislen(a), sl.vislen(b), cols)
                    self.assertEqual(sl.strip_ansi(a)[-1], sl.strip_ansi(b)[-1])
                p_on, p_off = sl.strip_ansi(on[1]), sl.strip_ansi(off[1])
                m = re.search("[▀▄x]", p_on)
                if m:
                    seen = True
                    self.assertEqual(p_on[:m.start()], p_off[:m.start()], cols)
                else:
                    self.assertEqual(on[1], off[1], cols)
        self.assertTrue(seen)


class TestRobotFrame(CreatureCase):
    """The robot in the big and tall layouts: a 9-cell box of braille on two
    text rows; nothing else moves."""
    ROW1 = sl.NEON_GREEN + "┌─" + sl.R + "x" * 20
    LOOK = {"seed": 11, "family": "robot", "color": None}

    def test_big_box_straddles_the_rows(self):
        for n2 in (10, 30):
            row2 = sl.NEON_GREEN + "└─" + sl.R + "y" * n2
            for mood in MOODS_ALL:
                for icon in ("", "!"):
                    for cols in range(41, 200, 13):
                        for now in (NOW, NOW + 1, NOW + 170):
                            pres = {"mood": mood, "bubble": "", "since": now - 7,
                                    "mood_since": now - 7, "icon": icon}
                            r1, r2 = sl._frame_big(self.ROW1, row2, cols, True, 50, now, pres,
                                                   self.LOOK)
                            b1 = sl._frame(self.ROW1, cols, "┐", True)
                            b2 = sl._frame(row2, cols, "┘", True)
                            label = (n2, mood, icon, cols, now)
                            self.assertEqual((sl.vislen(r1), sl.vislen(r2)), (cols, cols), label)
                            start = max(sl.vislen(self.ROW1), sl.vislen(row2)) + 1
                            track = cols - 1 - start
                            if track < 17:
                                self.assertEqual((r1, r2), (b1, b2), label)
                                continue
                            p = sl.robot_pose(11, mood, now - 7, now, track, None, icon)
                            top, bottom = sl.render_robot(p, rule_top=True)
                            col, w = start + p["pos"], sl.ROBOT_W
                            c1, c2 = _cells(sl.strip_ansi(r1)), _cells(sl.strip_ansi(r2))
                            k1, k2 = _cells(sl.strip_ansi(b1)), _cells(sl.strip_ansi(b2))
                            self.assertEqual(c1[col:col + w], _cells(sl.strip_ansi(top)), label)
                            self.assertEqual(c2[col:col + w], _cells(sl.strip_ansi(bottom)), label)
                            self.assertEqual(c2[:col] + c2[col + w:], k2[:col] + k2[col + w:], label)
                            self.assertEqual(c1[:col] + c1[col + w:], k1[:col] + k1[col + w:], label)
                            self.assertEqual((c1[-1], c2[-1]), ("┐", "┘"), label)

    def test_tall_head_line_and_row_1(self):
        for mood in MOODS_ALL:
            for cols in range(41, 200, 13):
                for now in (NOW, NOW + 1):
                    pres = {"mood": mood, "bubble": "", "since": now - 7, "mood_since": now - 7,
                            "icon": ""}
                    head, r1 = sl._frame_creature(self.ROW1, cols, True, 50, now, pres, self.LOOK)
                    b1 = sl._frame(self.ROW1, cols, "┐", True)
                    label = (mood, cols, now)
                    self.assertEqual(sl.vislen(r1), cols, label)
                    track = cols - sl.vislen(self.ROW1) - 2
                    if track < 17:
                        self.assertEqual((head, r1), (sl.R, b1), label)
                        continue
                    p = sl.robot_pose(11, mood, now - 7, now, track)
                    up, low = sl.render_robot(p)
                    col, w = sl.vislen(self.ROW1) + 1 + p["pos"], sl.ROBOT_W
                    c1, k1 = _cells(sl.strip_ansi(r1)), _cells(sl.strip_ansi(b1))
                    self.assertEqual(c1[col:col + w], _cells(sl.strip_ansi(low)), label)
                    self.assertEqual(c1[:col] + c1[col + w:], k1[:col] + k1[col + w:], label)
                    h = _cells(sl.strip_ansi(head))
                    self.assertEqual(h[col:col + w], _cells(sl.strip_ansi(up)), label)
                    self.assertEqual(set(h[:col]), {" "} if col else set(), label)

    def test_the_box_is_linked_on_both_rows(self):
        action = lambda name, text, extra="": sl.link("retro-hud://" + name, text)
        row2 = sl.NEON_GREEN + "└─" + sl.R + "y" * 10
        pres = {"mood": "working", "bubble": "ready", "since": NOW, "mood_since": None}
        r1, r2 = sl._frame_big(self.ROW1, row2, 120, True, 50, NOW, pres, self.LOOK, action)
        self.assertEqual((r1.count("retro-hud://card"), r2.count("retro-hud://card")), (1, 1))
        head, r1 = sl._frame_creature(self.ROW1, 120, True, 50, NOW, pres, self.LOOK, action)
        self.assertEqual((head.count("retro-hud://card"), r1.count("retro-hud://card")), (1, 1))

    def test_hud_robot_at_every_size(self):
        os.environ["RETRO_HUD_SPRITE"] = "robot"
        self.addCleanup(os.environ.pop, "RETRO_HUD_SPRITE", None)
        self.tx(user(NOW - 50), asst(NOW - 2, "tool_use"))
        seen = {}
        for size, n in (("tiny", 2), ("big", 2), ("tall", 3)):
            os.environ["RETRO_HUD_CREATURE"] = size
            for cols in range(50, 241, 10):
                for t in (NOW, NOW + 1, NOW + 30):
                    on = sl.render(self.payload(FULL), cols, t)
                    os.environ["RETRO_HUD_CREATURE"] = "0"
                    off = sl.render(self.payload(FULL), cols, t)
                    os.environ["RETRO_HUD_CREATURE"] = size
                    self.assertEqual(len(on), n, (size, cols))
                    for a, b in zip(on[-2:], off):
                        self.assertEqual(sl.vislen(a), sl.vislen(b), (size, cols))
                    plain = "\n".join(sl.strip_ansi(r) for r in on)
                    if _TINY_CELL.search(plain):
                        seen.setdefault(size, cols)
                        rows = [i for i, r in enumerate(on) if _TINY_CELL.search(sl.strip_ansi(r))]
                        self.assertEqual(len(rows), 1 if size == "tiny" else 2, (size, cols))
                        self.assertNotIn("▀", plain)
                        self.assertNotIn("▄", plain)
        self.assertEqual(set(seen), {"tiny", "big", "tall"})
        sl.render(self.payload(FULL), 160, NOW)
        self.assertEqual(self.state_file()["creature"], "robot")

    def test_robot_excursions_keep_the_rows_in_shape(self):
        os.environ["RETRO_HUD_EXCURSIONS"] = "1"
        self.addCleanup(os.environ.__setitem__, "RETRO_HUD_EXCURSIONS", "0")
        look = {"seed": 0, "family": "robot", "color": None}
        calm = {"mood": "calm", "bubble": "", "since": 0, "mood_since": None, "icon": ""}
        for kind in sl.EXCURSION_KINDS:
            p = _when(kind, 0)
            frames = [sl.excursion_rows("big", ExcursionCase.ROW1, ExcursionCase.ROW2, 100, True,
                                        30, t, calm, look)
                      for t in range(p["start"], p["start"] + p["dur"])]
            self.assertTrue(all(f is not None for f in frames), kind)
            for i, rows in enumerate(frames):
                for r, (lead, corner) in zip(rows, (("┌─", "┐"), ("└─", "┘"))):
                    plain = sl.strip_ansi(r)
                    self.assertEqual(sl.vislen(r), 100, (kind, i))
                    self.assertEqual((plain[:2], plain[-1]), (lead, corner), (kind, i))
                self.assertEqual(rows[0].count("\033]8;;https://example.com/b\a"), 1, (kind, i))
            self.assertTrue(any(_TINY_CELL.search(sl.strip_ansi(r[0]) + sl.strip_ansi(r[1]))
                                for r in frames), kind)


class TestCompositor(unittest.TestCase):
    """A row as visible cells, escapes attached; creature cells laid over
    them without moving anything."""
    LINK_OPEN = "\033]8;;https://example.com/b\a"
    LINK_CLOSE = "\033]8;;\a"
    ROW = (sl.NEON_GREEN + "┌─" + sl.R + sl.MODEL_BOX + "[" + sl.R + " X " +
           sl.MODEL_BOX + "]" + sl.R + sl.SEP + sl.NEON_WHT + "\U0001F4C2 dir" + sl.R +
           sl.SEP + sl.BRANCH_BADGE + " ⎇ " + LINK_OPEN + "main-branch" + LINK_CLOSE +
           " " + sl.R + " " + sl.RULE + "──────" + sl.R + sl.NEON_GREEN + "┐" + sl.R)
    CELL = "\033[38;5;46m⣿" + sl.R

    @staticmethod
    def escapes(s):
        return [m.group(0) for m in sl._ANSI_RE.finditer(s)]

    def test_split_round_trips_and_counts_cells(self):
        cells, tail = sl.split_cells(self.ROW)
        self.assertEqual(sl.join_cells(cells, tail), self.ROW)
        self.assertEqual(len(cells), sl.vislen(self.ROW))
        self.assertEqual(tail, sl.R)
        self.assertEqual(cells[0], [sl.NEON_GREEN, "┌"])
        i = [t for _, t in cells].index("\U0001F4C2")
        self.assertEqual(cells[i + 1], ["", ""])  # the emoji owns two cells

    def test_split_follows_the_emoji_width_knob(self):
        old = sl._EMOJI_W
        try:
            sl._EMOJI_W = 1
            cells, _ = sl.split_cells("a\U0001F4C2b")
            self.assertEqual([t for _, t in cells], ["a", "\U0001F4C2", "b"])
        finally:
            sl._EMOJI_W = old

    def test_overlay_keeps_width_and_every_escape_in_order(self):
        n = sl.vislen(self.ROW)
        for col in range(-3, n + 3):
            for k in (1, 3, 7, 30):
                out = sl.overlay(self.ROW, col, [self.CELL] * k)
                self.assertEqual(sl.vislen(out), n, (col, k))
                it = iter(self.escapes(out))  # the row's escapes, an ordered subsequence
                self.assertTrue(all(e in it for e in self.escapes(self.ROW)), (col, k))
                self.assertEqual(out.count(self.LINK_OPEN), 1)
                self.assertEqual(out.count(self.LINK_CLOSE), 1)
                self.assertLess(out.index(self.LINK_OPEN), out.index(self.LINK_CLOSE))

    def test_overlay_replaces_text_only(self):
        plain = sl.strip_ansi(self.ROW)
        out = sl.strip_ansi(sl.overlay(self.ROW, 4, [self.CELL] * 3))
        self.assertEqual(out[:4] + out[7:], plain[:4] + plain[7:])
        self.assertEqual(out[4:7], "⣿⣿⣿")

    def test_transparent_cells_leave_the_row_alone(self):
        self.assertEqual(sl.strip_ansi(sl.overlay(self.ROW, 3, [None, self.CELL, None])),
                         sl.strip_ansi(self.ROW)[:4] + "⣿" + sl.strip_ansi(self.ROW)[5:])

    def test_colour_and_link_across_the_overlay_stay_intact(self):
        cells, _ = sl.split_cells(self.ROW)
        texts = [t for _, t in cells]
        b = texts.index("m")  # inside the badge and the link
        out = sl.overlay(self.ROW, b, [self.CELL] * 3)
        after = out.index("n-branch")  # the first uncovered cell after the run
        before = out[:after]
        # the badge colour is set again before the next cell, after the reset
        self.assertTrue(before.endswith(sl.BRANCH_BADGE), repr(before[-40:]))
        # and the run itself sits between the link's open and close
        self.assertLess(out.index(self.LINK_OPEN), out.index("⣿"))
        self.assertGreater(out.index(self.LINK_CLOSE), after)

    def test_half_covered_wide_char_is_replaced_whole(self):
        cells, _ = sl.split_cells(self.ROW)
        i = [t for _, t in cells].index("\U0001F4C2")
        for col in (i, i + 1):  # cover only its first, or only its second, cell
            out = sl.overlay(self.ROW, col, [self.CELL])
            self.assertNotIn("\U0001F4C2", out, col)
            self.assertEqual(sl.vislen(out), sl.vislen(self.ROW), col)
            self.assertIn("⣿", out)
        out = sl.strip_ansi(sl.overlay(self.ROW, i + 1, [self.CELL]))
        self.assertEqual(out[i:i + 2], " ⣿")
        out = sl.strip_ansi(sl.overlay(self.ROW, i, [self.CELL]))
        self.assertEqual(out[i:i + 2], "⣿ ")

    def test_corners_and_leads_are_never_covered(self):
        n = sl.vislen(self.ROW)
        out = sl.strip_ansi(sl.overlay(self.ROW, 0, [self.CELL] * n))
        self.assertEqual(out[:2], "┌─")
        self.assertEqual(out[-1], "┐")
        self.assertEqual(set(out[2:-1]), {"⣿"})
        row2 = sl._frame(sl.NEON_GREEN + "└─" + sl.R + "42%", 30, "┘", True)
        out = sl.strip_ansi(sl.overlay(row2, 0, [self.CELL] * 30))
        self.assertEqual((out[:2], out[-1]), ("└─", "┘"))


class TestExcursionSchedule(unittest.TestCase):
    """One excursion per 10-minute bucket, 5–15 min apart, 4–20 s long,
    deterministic from (seed, time)."""

    def plans(self, seed, count=200):
        return [sl.excursion_plan(seed, NOW // 600 + b) for b in range(count)]

    def test_cadence_and_length(self):
        kinds = set()
        for seed in (0, 1, 7, 123456789):
            plans = self.plans(seed)
            starts = [p["start"] for p in plans]
            gaps = [b - a for a, b in zip(starts, starts[1:])]
            self.assertGreaterEqual(min(gaps), 5 * 60, seed)
            self.assertLessEqual(max(gaps), 15 * 60, seed)
            for p in plans:
                self.assertTrue(4 <= p["dur"] <= 20, p)
                self.assertEqual(p["start"] // 600, (p["start"] + p["dur"]) // 600, p)
                kinds.add(p["kind"])
            self.assertEqual(plans, self.plans(seed))
        self.assertEqual(kinds, set(sl.EXCURSION_KINDS))
        self.assertEqual(set(sl.EXCURSION_KINDS),
                         {"stretch", "peek", "crawl", "downstairs", "hang"})

    def test_active_exactly_during_the_excursion(self):
        p = sl.excursion_plan(3, NOW // 600)
        on = [t for t in range(NOW, NOW + 600) if sl.excursion_at(3, t)]
        self.assertEqual(on, list(range(p["start"], p["start"] + p["dur"])))
        for t in on:
            ex = sl.excursion_at(3, t)
            self.assertEqual((ex["kind"], ex["phase"], ex["n"]),
                             (p["kind"], t - p["start"], p["dur"]))

    def test_a_long_tick_still_shows_every_excursion(self):
        for tick_len in (2, 5, 7, 10):
            for b in range(40):
                p = sl.excursion_plan(9, NOW // 600 + b)
                seen = [sl.excursion_at(9, t, tick_len)
                        for t in range(p["start"] - 30, p["start"] + 60)]
                seen = [ex for ex in seen if ex]
                self.assertTrue(seen, (tick_len, b))
                self.assertTrue(all(ex["kind"] == p["kind"] for ex in seen))
                # one frame per tick: every second of a tick agrees
                for t in range(p["start"] - 30, p["start"] + 60):
                    base = t - t % tick_len
                    self.assertEqual(sl.excursion_at(9, t, tick_len),
                                     sl.excursion_at(9, base, tick_len))


def _when(kind, seed=0, sit=None):
    """The first excursion of `kind` from NOW on, for `seed`."""
    for b in range(NOW // 600, NOW // 600 + 1000):
        p = sl.excursion_plan(seed, b)
        if p["kind"] == kind and (sit is None or p["sit"] == sit):
            return p
    raise AssertionError(kind)


_TINY_CELL = re.compile("[⠁-⣿]")
_BIG_CELL = re.compile("[▀▄]")


def _creature_cols(plain, pat):
    return [i for i, ch in enumerate(_cells(plain)) if pat.match(ch)]


class ExcursionCase(CreatureCase):
    """Excursions on (the suite pins them off), a fixed seed and rows with
    a coloured, linked badge, a wide emoji and a cost field."""
    ROW1 = (sl.NEON_GREEN + "┌─" + sl.R + sl.MODEL_BOX + "[" + sl.R + " X " + sl.MODEL_BOX +
            "]" + sl.R + sl.SEP + sl.NEON_WHT + "\U0001F4C2 dir" + sl.R + sl.SEP +
            sl.BRANCH_BADGE + " ⎇ " + sl.link("https://example.com/b", "main") + " " + sl.R)
    ROW2 = sl.NEON_GREEN + "└─" + sl.R + "42%" + sl.SEP + sl.NEON_YEL + "$3.21" + sl.R
    LOOK = {"seed": 0, "family": "alien", "color": None}
    CALM = {"mood": "calm", "bubble": "", "since": 0, "mood_since": None, "icon": ""}

    def setUp(self):
        super().setUp()
        os.environ["RETRO_HUD_EXCURSIONS"] = "1"

    def tearDown(self):
        os.environ["RETRO_HUD_EXCURSIONS"] = "0"
        super().tearDown()

    def ex(self, size, now, cols=100, pres=None, look=None, row1=None, row2=None):
        return sl.excursion_rows(size, row1 or self.ROW1, row2 or self.ROW2, cols, True, 30,
                                 now, self.CALM if pres is None else pres, look or self.LOOK)

    def frames(self, size, kind, cols=100, sit=None, seed=0):
        p = _when(kind, seed, sit)
        look = dict(self.LOOK, seed=seed)
        return [self.ex(size, t, cols, look=look) for t in range(p["start"], p["start"] + p["dur"])]

    def check_frame(self, rows, cols, label):
        self.assertIsNotNone(rows, label)
        for r, (lead, corner) in zip(rows, (("┌─", "┐"), ("└─", "┘"))):
            plain = sl.strip_ansi(r)
            self.assertEqual(sl.vislen(r), cols, label)
            self.assertEqual((plain[:2], plain[-1]), (lead, corner), label)


class TestExcursionFrames(ExcursionCase):
    def test_every_kind_in_both_sizes_keeps_the_rows_in_shape(self):
        for size in ("tiny", "big"):
            for kind in sl.EXCURSION_KINDS:
                for cols in (60, 100, 173):
                    for i, rows in enumerate(self.frames(size, kind, cols)):
                        self.check_frame(rows, cols, (size, kind, cols, i))

    def test_link_and_badge_survive_every_frame(self):
        for size in ("tiny", "big"):
            for kind in sl.EXCURSION_KINDS:
                for rows in self.frames(size, kind):
                    self.assertEqual(rows[0].count("\033]8;;https://example.com/b\a"), 1)
                    self.assertEqual(rows[0].count("\033]8;;\a"), 1)
                    self.assertIn(sl.BRANCH_BADGE, rows[0])

    def test_stretch_doubles_the_body(self):
        normal = len(_creature_cols(sl.strip_ansi(sl._frame_tiny(
            self.ROW1, 100, True, 30, NOW, self.CALM, self.LOOK)), _TINY_CELL))
        widths = [len(_creature_cols(sl.strip_ansi(r[0]), _TINY_CELL))
                  for r in self.frames("tiny", "stretch")]
        self.assertGreaterEqual(max(widths), 2 * normal - 1, widths)
        def span(rows):
            return len(set(_creature_cols(sl.strip_ansi(rows[0]), _BIG_CELL)) |
                       set(_creature_cols(sl.strip_ansi(rows[1]), _BIG_CELL)))
        home = span(sl._frame_big(self.ROW1, self.ROW2, 100, True, 30, NOW, self.CALM,
                                  self.LOOK))
        big = [span(r) for r in self.frames("big", "stretch")]
        self.assertGreaterEqual(max(big), 2 * home - 2, (home, big))

    def test_peek_hides_behind_the_right_corner(self):
        frames = self.frames("tiny", "peek")
        seen = [_creature_cols(sl.strip_ansi(r[0]), _TINY_CELL) for r in frames]
        self.assertIn([], seen)  # behind the corner for a moment
        peeks = [c for c in seen if c and len(c) <= 3 and c[-1] == 98]
        self.assertTrue(peeks, seen)  # a sliver against the corner: eyes and arms

    def test_crawl_walks_over_the_words_and_back(self):
        frames = self.frames("tiny", "crawl")
        left = [min(_creature_cols(sl.strip_ansi(r[0]), _TINY_CELL) or [999]) for r in frames]
        self.assertEqual(min(left), 2)
        self.assertGreater(left[0], 30)
        self.assertGreater(left[-1], 20)
        mid = sl.strip_ansi(frames[left.index(2)][0])
        self.assertNotIn("[ X", mid)  # the model box is covered …
        self.assertTrue(all(sl.strip_ansi(r[1]) == sl.strip_ansi(
            sl._frame(self.ROW2, 100, "┘", True)) for r in frames))  # … row 2 is not
        big = [min(_creature_cols(sl.strip_ansi(r[0]), _BIG_CELL) or [999])
               for r in self.frames("big", "crawl")]
        self.assertEqual(min(big), 2)

    def test_downstairs_visits_row_2_and_may_sit_on_the_cost(self):
        for sit in (True, False):
            frames = self.frames("tiny", "downstairs", sit=sit)
            down = [r for r in frames if _creature_cols(sl.strip_ansi(r[1]), _TINY_CELL)
                    and not _creature_cols(sl.strip_ansi(r[0]), _TINY_CELL)]
            self.assertTrue(down, sit)
            covered = [r for r in down if "$3.21" not in sl.strip_ansi(r[1])]
            self.assertEqual(bool(covered), sit)
            self.assertTrue(_creature_cols(sl.strip_ansi(frames[0][0]), _TINY_CELL))
            self.assertTrue(_creature_cols(sl.strip_ansi(frames[-1][0]), _TINY_CELL))
        big = self.frames("big", "downstairs")
        self.assertTrue(any(_creature_cols(sl.strip_ansi(r[1]), _BIG_CELL) and not
                            _creature_cols(sl.strip_ansi(r[0]), _BIG_CELL) for r in big))

    def test_hang_dangles_upside_down_under_the_corner(self):
        frames = self.frames("tiny", "hang")
        hung = [r for r in frames if _creature_cols(sl.strip_ansi(r[1]), _TINY_CELL)]
        self.assertTrue(hung)
        for r in hung:
            self.assertGreaterEqual(max(_creature_cols(sl.strip_ansi(r[1]), _TINY_CELL)), 96)
        p = sl.tiny_pose(0, "calm", None, NOW, 50)
        flipped = [ch for ch in sl.braille(p["dots"][::-1]) if ch]
        self.assertTrue(any(set(flipped) & set(sl.strip_ansi(r[1])) for r in hung))
        big = self.frames("big", "hang")
        self.assertTrue(any(_creature_cols(sl.strip_ansi(r[0]), _BIG_CELL) and
                            max(_creature_cols(sl.strip_ansi(r[0]), _BIG_CELL)) >= 96
                            for r in big))

    def test_frames_are_pure_and_differ_from_home(self):
        for kind in sl.EXCURSION_KINDS:
            p = _when(kind)
            t = p["start"] + p["dur"] // 2
            self.assertEqual(self.ex("tiny", t), self.ex("tiny", t))
            home = (sl._frame_tiny(self.ROW1, 100, True, 30, t, self.CALM, self.LOOK),
                    sl._frame(self.ROW2, 100, "┘", True))
            self.assertNotEqual(self.ex("tiny", t), home, kind)
            self.assertIsNone(self.ex("tiny", p["start"] - 1))
            self.assertIsNone(self.ex("tiny", p["start"] + p["dur"]))


class TestExcursionGates(ExcursionCase):
    def active(self):
        p = _when("crawl")
        return p["start"] + 3

    def test_only_calm_idle_and_yours_go_exploring(self):
        t = self.active()
        for mood in MOODS_ALL:
            pres = dict(self.CALM, mood=mood)
            got = self.ex("tiny", t, pres=pres)
            if mood in ("calm", "idle", "yours"):
                self.assertIsNotNone(got, mood)
            else:
                self.assertIsNone(got, mood)
        # gauge-only: calm under 70%, never amber or red
        for pct, on in ((30, True), (75, False), (95, False)):
            got = sl.excursion_rows("tiny", self.ROW1, self.ROW2, 100, True, pct, t, None,
                                    self.LOOK)
            self.assertEqual(got is not None, on, pct)

    def test_a_bubble_or_an_icon_keeps_it_home(self):
        t = self.active()
        self.assertIsNone(self.ex("tiny", t, pres=dict(self.CALM, bubble="hello")))
        self.assertIsNone(self.ex("tiny", t, pres=dict(self.CALM, icon="!")))

    def test_off_switches(self):
        t = self.active()
        self.assertIsNone(self.ex("tall", t))
        self.assertIsNone(self.ex("off", t))
        self.assertIsNone(sl.excursion_rows("tiny", self.ROW1, self.ROW2, 100, False, 30, t,
                                            self.CALM, self.LOOK))
        self.assertIsNone(sl.excursion_rows("tiny", self.ROW1, self.ROW2, 100, True, None, t,
                                            self.CALM, self.LOOK))
        self.assertIsNone(self.ex("tiny", t, cols=sl.vislen(self.ROW1) + 1 + sl.TINY_MIN_TRACK))
        n = sl.vislen(self.ROW1)
        self.assertIsNone(self.ex("big", t, cols=n + 1 + sl.CREATURE_MIN_TRACK))
        self.assertIsNotNone(self.ex("big", t, cols=n + 2 + sl.CREATURE_MIN_TRACK))
        os.environ["RETRO_HUD_EXCURSIONS"] = "0"
        self.assertIsNone(self.ex("tiny", t))

    def test_render_knob_off_is_byte_identical(self):
        os.environ["RETRO_HUD_CREATURE_SEED"] = "0"
        for size in ("tiny", "big"):
            os.environ["RETRO_HUD_CREATURE"] = size
            for kind in sl.EXCURSION_KINDS:
                p = _when(kind)
                for t in (p["start"], p["start"] + p["dur"] // 2):
                    on = sl.render(self.payload(MINIMAL), 120, t)
                    os.environ["RETRO_HUD_EXCURSIONS"] = "0"
                    off = sl.render(self.payload(MINIMAL), 120, t)
                    os.environ["RETRO_HUD_EXCURSIONS"] = "1"
                    saved = sl.excursion_at
                    sl.excursion_at = lambda *a, **k: None
                    try:
                        never = sl.render(self.payload(MINIMAL), 120, t)
                    finally:
                        sl.excursion_at = saved
                    self.assertEqual(off, never, (size, kind))
                    self.assertNotEqual(on, off, (size, kind, t))
                    for a, b in zip(on, off):
                        self.assertEqual(sl.vislen(a), sl.vislen(b))
            os.environ["RETRO_HUD_CREATURE"] = "tall"
            p = _when("crawl")
            on = sl.render(self.payload(MINIMAL), 120, p["start"] + 2)
            os.environ["RETRO_HUD_EXCURSIONS"] = "0"
            self.assertEqual(on, sl.render(self.payload(MINIMAL), 120, p["start"] + 2))
            os.environ["RETRO_HUD_EXCURSIONS"] = "1"

    def test_working_never_leaves_in_the_full_hud(self):
        os.environ["RETRO_HUD_CREATURE"] = "tiny"
        os.environ["RETRO_HUD_CREATURE_SEED"] = "0"
        p = _when("downstairs")
        t = p["start"] + 5
        self.tx(user(t - 50), asst(t - 2, "tool_use"))
        on = sl.render(self.payload(FULL), 160, t)
        os.environ["RETRO_HUD_EXCURSIONS"] = "0"
        self.assertEqual(on, sl.render(self.payload(FULL), 160, t))

    def test_tick_s_5_shows_it_and_holds_each_frame(self):
        os.environ["RETRO_HUD_CREATURE"] = "tiny"
        os.environ["RETRO_HUD_CREATURE_SEED"] = "0"
        os.environ["RETRO_HUD_TICK_S"] = "5"
        p = _when("crawl")
        t0 = p["start"] - p["start"] % 5 + 5
        a = [sl.render(self.payload(MINIMAL), 120, t0 + i) for i in range(5)]
        self.assertEqual(len({tuple(x) for x in a}), 1)
        os.environ["RETRO_HUD_EXCURSIONS"] = "0"
        self.assertNotEqual(a[0], sl.render(self.payload(MINIMAL), 120, t0))


class TestCreatureCLI(unittest.TestCase):
    SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "statusline.py")

    def run_script(self, stdin_bytes, creature, *args):
        env = dict(os.environ, COLUMNS="120", RETRO_HUD_CREATURE=creature)
        return subprocess.run([sys.executable, self.SCRIPT] + list(args),
                              input=stdin_bytes, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=env, timeout=10)

    def test_line_counts(self):
        for creature, newlines in (("tall", 2), ("big", 1), ("tiny", 1), ("", 1), ("0", 1)):
            for stdin, args in ((b"", ()), (b"{not json", ()), (b"", ("--demo",))):
                p = self.run_script(stdin, creature, *args)
                self.assertEqual(p.returncode, 0, p.stderr.decode())
                self.assertEqual(p.stderr, b"")
                self.assertEqual(p.stdout.count(b"\n"), newlines, (creature, stdin, args))

    def test_robot_demo_is_braille_on_two_rows(self):
        for creature, newlines in (("big", 1), ("tall", 2)):
            env = dict(os.environ, COLUMNS="160", RETRO_HUD_CREATURE=creature, RETRO_HUD_SPRITE="robot")
            p = subprocess.run([sys.executable, self.SCRIPT, "--demo"], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=env, timeout=10)
            self.assertEqual(p.returncode, 0, p.stderr.decode())
            out = p.stdout.decode()
            self.assertEqual(out.count("\n"), newlines, creature)
            rows = [sl.strip_ansi(r) for r in out.split("\n")]
            self.assertEqual(sum(1 for r in rows if _TINY_CELL.search(r)), 2, (creature, rows))

    def test_degraded_fallback_keeps_three_lines(self):
        import contextlib
        import io
        saved = sl.render
        sl.render = lambda *a: 1 / 0
        os.environ["RETRO_HUD_CREATURE"] = "tall"
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                sl.main(["--demo"])
            lines = buf.getvalue().split("\n")
            self.assertEqual(len(lines), 3)
            self.assertEqual(lines[0], sl.R)
            self.assertIn("(status degraded)", lines[2])
        finally:
            sl.render = saved
            os.environ["RETRO_HUD_CREATURE"] = "0"


class TestHelpers(unittest.TestCase):
    def test_short_duration_and_cost(self):
        d = sl.fmt_short_dur
        self.assertEqual([d(0), d(4 * 60000), d(47 * 60000), d(58 * 60000)], ["0m", "4m", "45m", "1h"])
        self.assertEqual([d(90 * 60000), d(89 * 60000), d(25 * 3600000 + 16 * 60000)], ["2h", "1h", "25h"])
        c = sl.fmt_short_cost
        self.assertEqual([c(0), c(0.37), c(3.21), c(5.43), c(20.8), c(99.6), c(208), c(995), c(1234)],
                         ["$0.0", "$0.4", "$3.2", "$5.4", "$21", "$100", "$210", "$1000", "$1.2k"])

    def test_trunc_by_visible_width(self):
        self.assertEqual(sl.trunc("abcdefgh", 5), "abc..")
        self.assertEqual(sl.trunc("abc", 5), "abc")
        self.assertLessEqual(sl.vwidth(sl.trunc("📂📂📂📂", 5)), 5)  # wide chars

    def test_fmt_countdown(self):
        self.assertEqual(sl.fmt_countdown(0), "0m")
        self.assertEqual(sl.fmt_countdown(59), "1m")
        self.assertEqual(sl.fmt_countdown(3600), "1h")
        self.assertEqual(sl.fmt_countdown(5400), "1h30m")
        self.assertEqual(sl.fmt_countdown(90000), "1d1h")

    def test_fmt_tok(self):
        self.assertEqual(sl.fmt_tok(999), "999")
        self.assertEqual(sl.fmt_tok(84213), "84.2K")
        self.assertEqual(sl.fmt_tok(1_333_332), "1.3M")
        self.assertEqual(sl.fmt_win(200000), "200K")
        self.assertEqual(sl.fmt_win(1_000_000), "1M")

    def test_git_branch_this_repo(self):
        here = os.path.dirname(os.path.abspath(__file__))
        self.assertNotEqual(sl.git_branch(here), "")


class TestCLI(unittest.TestCase):
    SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "statusline.py")

    def run_script(self, stdin_bytes, *args):
        env = dict(os.environ, COLUMNS="120")
        return subprocess.run([sys.executable, self.SCRIPT] + list(args),
                              input=stdin_bytes, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=env, timeout=10)

    def test_empty_stdin_no_crash(self):
        p = self.run_script(b"")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(p.stderr, b"")
        self.assertGreater(len(p.stdout), 0)

    def test_garbage_stdin_no_crash(self):
        p = self.run_script(b"{not json!!")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertEqual(p.stderr, b"")

    def test_version_flag(self):
        p = self.run_script(b"", "--version")
        self.assertIn(sl.__version__.encode(), p.stdout)

    def test_demo_flag(self):
        p = self.run_script(b"", "--demo")
        self.assertEqual(p.returncode, 0, p.stderr.decode())
        self.assertIn(b"Fable 5", p.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
