def url_join(base: str, *parts: str) -> str:
    return "/".join([base, *parts])
