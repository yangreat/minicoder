import pytest
from inventory import Inventory

def test_remove_to_zero_deletes():
    inv = Inventory(); inv.add("a", 2); inv.remove("a", 2)
    assert "a" not in inv.items

def test_remove_too_many():
    inv = Inventory(); inv.add("a", 1)
    with pytest.raises(ValueError):
        inv.remove("a", 5)

def test_total_value():
    inv = Inventory(); inv.add("a", 3); inv.add("b", 2)
    assert inv.total_value({"a": 1.5, "b": 10}) == 24.5
