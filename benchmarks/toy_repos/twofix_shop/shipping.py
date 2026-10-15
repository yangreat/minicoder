def shipping_cost(weight_kg):
    if weight_kg < 1:
        return 5.0
    return 5.0 + 2.0 * int(weight_kg - 1)
