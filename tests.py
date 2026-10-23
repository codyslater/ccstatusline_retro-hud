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
           "RETRO_HUD_ALIEN"):
    os.environ.pop(_k, None)
_SUITE_TMP = tempfile.mkdtemp(prefix="retro-hud-tests-")
os.environ["RETRO_HUD_CACHE_DIR"] = os.path.join(_SUITE_TMP, "cache")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import statusline as sl

# Click actions are opt-in; a developer's own shell may export the toggle
# (and usually runs inside tmux), so every test starts from "off".
os.environ.pop("RETRO_HUD_ACTIONS", None)

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


class TestClickActionLinks(unittest.TestCase):
    """RETRO_HUD_ACTIONS=1 wraps segments in retro-hud:// OSC 8 links."""
    # sha256 of "\n".join(render(payload, cols, NOW)) as rendered by v2.7.0.
    # With actions off the output must stay byte-identical, even in tmux.
    GOLDEN = {
        "FULL": {
            60: "cc59a504bdf88a19651e861bf4c70a2c8998ce4c4283268444291d3bb3dcec64",
            100: "9e54e4c8ea31cdd2be077a306755e33fff053e9d5183b59a1ed101a46bc12682",
            160: "4b35578c5f291ba954f0aa8c233feb9cd322c7f8074649f30ae8314612e37573",
            220: "03b04902deb4e7809295836b812780ce0b7b51a458627e2af4edb088b2f00622"},
        "MINIMAL": {
            60: "5671daa0bac893ad6805e3705e3025795fe35ef547c2c52b1a84a6bf8a5726ee",
            100: "3818f0574300890d7bc522751e1a0a0089b4b5e77980d22a76efd5bb65cca6e2",
            160: "816b8ff61d4286f678970bae77a9893b1b0e334dd1f9e9e69ab7e63aafbdcc8e",
            220: "ccb305097189923e0078fcba5918b534e5846d89295a937e5b04420a604ab989"},
        "OVERLOAD": {
            60: "5ed1fb4dc5b73ab081fd1b68aa5e57634a0610edbb93c9527664625c23e10ddf",
            100: "83362b5e8c99343deb6decb4ba56a2e49c79250f45cbb1a77aa3a3a4b56a3ca4",
            160: "98be41c46e09ad289439cbe37776d718a9fb93e620d70ee6d4e24d5f4759ba44",
            220: "e8845c761adb2e5500a400a976366ef11baaae59ec0b3e2d7751e0c1051c8b75"},
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
        self.assertEqual(found["cost"], [(1, "retro-hud://cost?" + self.Q, "$3.21")])
        self.assertEqual(found["diff"], [(1, "retro-hud://diff?" + self.Q, "+128/-37")])
        (row, url, text), = found["usage"]
        self.assertEqual((row, url), (1, "retro-hud://usage?" + self.Q))
        self.assertIn("63%", text)
        self.assertIn("81% · 3d", text)
        (row, url, text), = found["agent"]  # the alien on the top rule
        self.assertEqual((row, url), (0, "retro-hud://agent?" + self.Q))
        self.assertIn(text, [f for pair in sl.ALIEN_FRAMES for f in pair])
        self.assertEqual(set(found),
                         {"model", "effort", "ctx", "cost", "diff", "usage", "agent"})

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
              "#{pane_current_path}": os.environ.get("FAKE_TMUX_PANE_PATH", ""),
              "#{pane_id}": os.environ.get("FAKE_TMUX_ACTIVE_PANE", "%7")}
    sys.stdout.write(answer.get(cmd[-1], "") + "\n")
elif cmd[:1] == ["show-options"]:
    sys.stdout.write(os.environ.get("FAKE_TMUX_FEATURES", "") + "\n")
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
            opts[argv[i]] = argv[i + 1]
            i += 2
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
                    "retro-hud://cost?pane=%257\n", "RETRO-HUD://cost"):
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
                     "--no-pager", "--no-ext-diff", "--no-textconv", "LESSSECURE=1"):
            self.assertIn(flag, cmd)

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

    def test_agent_is_accepted_but_reserved(self):
        p = self.run_handler(self.url("agent"))
        self.assertEqual(p.returncode, 0)
        self.assertEqual(self.tmux_calls(), [])
        self.assertNotIn("reject", self.handler_log())

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
        return re.findall(r"\x1b\]8;;(retro-hud://agent[^\x07]*)\x07(.*?)\x1b\]8;;\x07", row)

    def test_sprite_is_linked_and_the_bubble_is_not(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.events({"ts": NOW, "text": "deploy finished", "ttl": 600})
        self.actions_on()
        row = sl.render(self.payload(), 160, NOW)[0]
        (url, text), = self.agent_links(row)
        self.assertEqual(url, "retro-hud://agent?pane=%257&sock=/tmp/tmux-1000/default")
        self.assertIn(sl.strip_ansi(text), sl.SPRITES["alien"]["working"])
        self.assertIn("deploy finished", sl.strip_ansi(row))
        self.assertNotIn("deploy", "".join(t for _, t in self.agent_links(row)))

    def test_no_agent_link_outside_tmux_or_when_off(self):
        self.tx(asst(NOW - 2, "tool_use"))
        self.assertEqual(self.agent_links(sl.render(self.payload(), 160, NOW)[0]), [])
        os.environ["RETRO_HUD_ACTIONS"] = "1"
        self.assertEqual(self.agent_links(sl.render(self.payload(), 160, NOW)[0]), [])

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
