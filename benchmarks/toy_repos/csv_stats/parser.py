def parse_csv(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        rows.append(line.split(","))
    return rows
