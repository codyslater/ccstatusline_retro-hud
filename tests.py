#!/usr/bin/env python3
"""retro-hud test suite — stdlib only. Run: python3 tests.py"""
import copy
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import statusline as sl

NOW = 1_800_000_000

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
                       "· 3d", "+128", "-37", "cache 95%", "T:1h30m", "$3.21",
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
        60: "cc59a504bdf88a19651e861bf4c70a2c8998ce4c4283268444291d3bb3dcec64",
        100: "9e54e4c8ea31cdd2be077a306755e33fff053e9d5183b59a1ed101a46bc12682",
        160: "4b35578c5f291ba954f0aa8c233feb9cd322c7f8074649f30ae8314612e37573",
        220: "03b04902deb4e7809295836b812780ce0b7b51a458627e2af4edb088b2f00622",
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


class TestHelpers(unittest.TestCase):
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
