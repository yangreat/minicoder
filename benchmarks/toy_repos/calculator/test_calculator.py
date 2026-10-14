"""Tests for calculator - currently failing."""

import pytest
from calculator import calculator


def test_add() -> None:
    assert calculator(2, 3, "add") == 5


def test_subtract() -> None:
    assert calculator(5, 3, "subtract") == 2


def test_multiply() -> None:
    assert calculator(4, 5, "multiply") == 20


def test_divide() -> None:
    assert calculator(10, 2, "divide") == 5


def test_divide_by_zero() -> None:
    """This test should pass but currently fails."""
    with pytest.raises(ZeroDivisionError):
        calculator(10, 0, "divide")
