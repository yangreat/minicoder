from dataclasses import dataclass, field


@dataclass
class Todo:
    id: int
    title: str
    tags: str = ""
    done: bool = False
    extra: dict = field(default_factory=dict)
