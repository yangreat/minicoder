# Calculator Bug

This toy repository contains a calculator with a bug.

## The Bug

The calculator doesn't handle division by zero properly - it raises a raw ZeroDivisionError instead of checking first.

## Expected Fix

The calculator should check if the divisor is zero before performing division and raise a ValueError with a clear message.

## Tests

Run `pytest test_calculator.py` to see the failing test.
