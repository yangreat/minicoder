from text_stats import word_count, most_common

def test_word_count_simple():
    assert word_count("a b c") == 3

def test_word_count_spaces():
    assert word_count("  hello   world  ") == 2

def test_most_common_case():
    assert most_common("Apple apple banana") == "apple"

def test_most_common_tie():
    assert most_common("pear fig") == "fig"
