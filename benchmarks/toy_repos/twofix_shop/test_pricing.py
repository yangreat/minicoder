import pytest
from pricing import apply_discount
def test_discount(): assert apply_discount(200, 25) == 150.0
def test_zero(): assert apply_discount(9.99, 0) == 9.99
def test_bad():
    with pytest.raises(ValueError): apply_discount(10, 150)
