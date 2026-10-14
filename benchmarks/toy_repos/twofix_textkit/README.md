# Textkit (two independent bugs)
1. `slug.py`: `slugify(s)` lowercases, replaces runs of non-alphanumeric chars with a single `-`, and strips leading/trailing `-` ("Hello, World!" -> "hello-world").
2. `trunc.py`: `truncate(s, n)` returns s unchanged if len(s) <= n, else the first n-3 chars + "..." (total length n).
Run `pytest` to see failures in `test_slug.py` and `test_trunc.py`.
