# Inventory Bug

`Inventory.remove(item, qty)` must raise `ValueError` if removing more than is in stock, and must delete the item when its quantity reaches 0. `total_value(prices)` sums qty*price. Run `pytest` to see failures.
