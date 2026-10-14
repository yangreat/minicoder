from parser import parse_csv
from stats import column_mean


def test_quoted_comma():
    text = 'name,note\n"a,b",ok\n'
    rows = parse_csv(text)
    assert rows[1][0] == "a,b"
    assert rows[1][1] == "ok"


def test_mean_skips_blank():
    text = "n\n1\n\n3\n"
    assert column_mean(text, 0) == 2.0
