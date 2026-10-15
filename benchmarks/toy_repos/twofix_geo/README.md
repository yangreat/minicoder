# Geo (two independent bugs)
1. `distance.py`: `manhattan(p, q)` returns |x1-x2| + |y1-y2|.
2. `bbox.py`: `bbox(points)` returns (min_x, min_y, max_x, max_y) over all points; empty list raises ValueError.
Run `pytest` to see failures in `test_distance.py` and `test_bbox.py`.
