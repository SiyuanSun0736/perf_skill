from __future__ import annotations

import unittest

from perf_skill.parser import build_request, parse_statement


class ParseStatementTest(unittest.TestCase):
    def test_parse_chinese_statement(self) -> None:
        pid, comm, events = parse_statement("追踪 comm=python pid=4242 inst cycles")

        self.assertEqual(pid, 4242)
        self.assertEqual(comm, "python")
        self.assertEqual(events, ("instructions", "cycles"))

    def test_parse_bare_target_tokens(self) -> None:
        pid, comm, events = parse_statement("observe nginx 31337 instructions")

        self.assertEqual(pid, 31337)
        self.assertEqual(comm, "nginx")
        self.assertEqual(events, ("instructions", "cycles"))

    def test_build_request_applies_event_override(self) -> None:
        request = build_request(
            "trace comm=python pid=4242 inst",
            pid=None,
            comm=None,
            extra_events=["cache-misses"],
            interval_ms=500,
            history_size=10,
        )

        self.assertEqual(request.events, ("instructions", "cycles", "cache-misses"))
        self.assertEqual(request.interval_ms, 500)
        self.assertEqual(request.history_size, 10)


if __name__ == "__main__":
    unittest.main()
