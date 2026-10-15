# Shop (two independent bugs)
Two unrelated modules each have a bug:
1. `pricing.py`: `apply_discount(price, pct)` must return `price * (1 - pct/100)` rounded to 2 decimals; pct outside 0..100 raises ValueError.
2. `shipping.py`: `shipping_cost(weight_kg)` is 5.0 for weight <= 1, else 5.0 + 2.0 per started extra kg (e.g. 1.2 kg -> 7.0, 3 kg -> 9.0).
Run `pytest` to see failures in `test_pricing.py` and `test_shipping.py`.
