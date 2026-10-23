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
