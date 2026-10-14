from node import Node


class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.map = {}

    def get(self, key):
        if key not in self.map:
            return -1
        return self.map[key].value

    def put(self, key, value):
        self.map[key] = Node(key, value)
        if len(self.map) > self.capacity:
            first = next(iter(self.map))
            del self.map[first]
