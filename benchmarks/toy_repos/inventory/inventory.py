class Inventory:
    def __init__(self):
        self.items = {}

    def add(self, item, qty):
        self.items[item] = self.items.get(item, 0) + qty

    def remove(self, item, qty):
        self.items[item] = self.items.get(item, 0) - qty

    def total_value(self, prices):
        total = 0
        for item, qty in self.items.items():
            total += prices[item]
        return total
