from __future__ import annotations

import pytest

from envxx.versions import best_match, is_exact_query, parse_version, version_key


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("3.11.9", (3, 11, 9)),
        ("v22.14.0", (22, 14, 0)),
        ("22", (22,)),
        ("3.16.0a2", (3, 16, 0)),
        ("nope", ()),
    ],
)
def test_parse_version(raw, expected):
    assert parse_version(raw) == expected


def test_best_match_prefix():
    candidates = ["3.11.18", "3.11.9", "3.12.1", "3.10.14"]
    assert best_match(candidates, "3.11") == "3.11.18"
    assert best_match(candidates, "3.11.9") == "3.11.9"
    assert best_match(candidates, "3") == "3.12.1"
    assert best_match(candidates, "3.13") is None


def test_best_match_numeric_not_lexical():
    candidates = ["3.9.18", "3.10.4"]
    assert best_match(candidates, "3") == "3.10.4"


def test_exact_query():
    assert is_exact_query("3.11.9")
    assert not is_exact_query("3.11")
    assert not is_exact_query("22")


def test_version_key_ordering():
    values = ["3.9.18", "3.10.1", "3.10.0"]
    assert sorted(values, key=version_key) == ["3.9.18", "3.10.0", "3.10.1"]
