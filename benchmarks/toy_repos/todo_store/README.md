# Todo Store Bug (multi-file)

`Store.add(title, tags)` stores a todo. `Store.remove(id)` must raise `KeyError` if the id is missing. `query.by_tag(todos, tag)` must match whole tags, not substrings of a joined string. Files: `models.py`, `store.py`, `query.py`. Run `pytest` to see failures.
