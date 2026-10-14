# URL Join Bug

`url_join(base, *parts)` should join URL path segments, collapsing duplicate slashes and treating a part that starts with `/` as relative to the host (not a second scheme-relative path). Trailing slashes on intermediate parts should not duplicate. Run `pytest` to see failures.
