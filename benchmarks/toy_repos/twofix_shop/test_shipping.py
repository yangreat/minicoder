from shipping import shipping_cost
def test_light(): assert shipping_cost(1) == 5.0
def test_partial(): assert shipping_cost(1.2) == 7.0
def test_three(): assert shipping_cost(3) == 9.0
