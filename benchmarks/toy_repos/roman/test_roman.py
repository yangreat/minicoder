from roman import roman_to_int


def test_additive():
    assert roman_to_int("III") == 3
    assert roman_to_int("LVIII") == 58


def test_subtractive():
    assert roman_to_int("IV") == 4
    assert roman_to_int("IX") == 9
    assert roman_to_int("MCMXC") == 1990
