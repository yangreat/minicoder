from lru import LRUCache


def test_get_missing():
    c = LRUCache(1)
    assert c.get(1) == -1


def test_evict_least_recently_used():
    c = LRUCache(2)
    c.put(1, 1)
    c.put(2, 2)
    assert c.get(1) == 1
    c.put(3, 3)
    assert c.get(2) == -1
    assert c.get(1) == 1
    assert c.get(3) == 3
