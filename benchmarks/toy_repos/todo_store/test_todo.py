import pytest
from query import by_tag
from store import Store


def test_remove_missing():
    s = Store()
    with pytest.raises(KeyError):
        s.remove(99)


def test_tag_not_substring():
    s = Store()
    s.add("x", tags=["ab"])
    assert by_tag(s.items, "a") == []
    assert len(by_tag(s.items, "ab")) == 1
