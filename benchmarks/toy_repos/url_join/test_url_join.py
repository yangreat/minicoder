from url_join import url_join


def test_simple():
    assert url_join("http://ex.com", "a", "b") == "http://ex.com/a/b"


def test_trailing_slash_on_base():
    assert url_join("http://ex.com/", "api") == "http://ex.com/api"


def test_absolute_part():
    assert url_join("http://ex.com/old", "/api") == "http://ex.com/api"
