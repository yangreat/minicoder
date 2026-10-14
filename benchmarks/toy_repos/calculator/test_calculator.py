"""Tests for calculator - currently failing on divide-by-zero."""

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
    """Must raise ValueError (not ZeroDivisionError) when dividing by zero."""
    with pytest.raises(ValueError, match="zero"):
        calculator(10, 0, "divide")
