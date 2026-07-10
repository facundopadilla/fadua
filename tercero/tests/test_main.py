"""Tests for app.main — CLI argument parsing.

Focused on --watch validation: `--watch 0` (or a negative value) is
not a valid polling interval and must be rejected at parse time, not
silently treated as "watch disabled" (that behavior belongs
exclusively to omitting --watch entirely).
"""

from __future__ import annotations

import pytest

from app.main import build_parser


class TestWatchArgument:
    def test_watch_omitted_defaults_to_none(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.watch is None

    def test_watch_positive_value_is_accepted(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--watch", "30"])
        assert args.watch == 30

    def test_watch_zero_is_rejected(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["run", "--watch", "0"])

    def test_watch_negative_is_rejected(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["run", "--watch", "-5"])
