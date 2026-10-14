from trunc import truncate
def test_short(): assert truncate("abc", 3) == "abc"
def test_long(): assert truncate("abcdefghij", 6) == "abc..."
def test_len(): assert len(truncate("x" * 50, 10)) == 10
