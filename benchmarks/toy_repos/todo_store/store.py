from models import Todo


class Store:
    def __init__(self):
        self.items: list[Todo] = []

    def add(self, title: str, tags: list[str] | None = None) -> Todo:
        todo = Todo(id=len(self.items) + 1, title=title, tags=",".join(tags or []))
        self.items.append(todo)
        return todo

    def remove(self, todo_id: int) -> None:
        self.items = [t for t in self.items if t.id != todo_id]
