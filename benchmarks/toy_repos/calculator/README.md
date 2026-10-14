# Calculator Bug

This toy repository contains a calculator with a bug.

## The Bug

Division by zero currently raises a raw `ZeroDivisionError` from `a / b`. Tests (and this README) require a checked `ValueError` instead.

## Expected Fix

The calculator should check if the divisor is zero before performing division and raise a `ValueError` with a message containing `"zero"` (for example `"Cannot divide by zero"`).

## Tests

Run `pytest test_calculator.py` to see the failing test.
