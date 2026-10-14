from parser import parse_csv


def column_mean(text: str, col: int) -> float:
    rows = parse_csv(text)
    data = rows[1:] if rows and not _is_float(rows[0][col] if rows[0] else "") else rows
    vals = [float(r[col]) for r in data]
    return sum(vals) / len(vals)


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False
