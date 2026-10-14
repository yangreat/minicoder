def word_count(text: str) -> int:
    return len(text.split(" "))


def most_common(text: str) -> str:
    counts = {}
    for w in text.split():
        counts[w] = counts.get(w, 0) + 1
    return max(counts, key=lambda w: counts[w])
