from palindrome import is_palindrome


def test_simple():
    assert is_palindrome("racecar") is True
    assert is_palindrome("hello") is False


def test_case_and_spaces():
    assert is_palindrome("Race car") is True


def test_punctuation():
    assert is_palindrome("A man, a plan, a canal: Panama") is True
