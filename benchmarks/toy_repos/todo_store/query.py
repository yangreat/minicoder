from models import Todo


def by_tag(todos: list[Todo], tag: str) -> list[Todo]:
    return [t for t in todos if tag in t.tags]
