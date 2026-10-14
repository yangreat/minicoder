"""Apply unified diffs and SEARCH/REPLACE edits.

``difflib.restore`` is *not* a unified-diff applier (it expects
``difflib.Differ.compare`` output). Using it on a real ``@@`` hunk can replace
a source file with a fragment of the patch. This module implements actual
unified-diff application and a robust search/replace mode, both of which fail
with a clear error on mismatch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class PatchError(ValueError):
    """Raised when a patch cannot be applied cleanly."""


@dataclass
class Hunk:
    """One ``@@ -l,s +l,s @@`` hunk."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str]


HUNK_HEADER = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")


def apply_patch_text(original: str, patch: str) -> str:
    """Apply a unified-diff or SEARCH/REPLACE patch to ``original``.

    Returns the modified text. Raises :class:`PatchError` on mismatch or
    malformed input. Never silently writes a patch fragment as file contents.
    """
    if patch is None or not str(patch).strip():
        raise PatchError("Empty patch")

    if _looks_like_search_replace(patch):
        return apply_search_replace(original, patch)
    if _looks_like_unified_diff(patch):
        return apply_unified_diff(original, patch)
    raise PatchError(
        "Patch is neither a unified diff (expected '@@' hunk headers) "
        "nor a SEARCH:/REPLACE: block"
    )


def _looks_like_search_replace(patch: str) -> bool:
    return "SEARCH:" in patch and "REPLACE:" in patch


def _looks_like_unified_diff(patch: str) -> bool:
    return bool(HUNK_HEADER.search(patch)) or any(
        line.startswith("@@") for line in patch.splitlines()
    )


def apply_search_replace(original: str, patch: str) -> str:
    """Apply one or more SEARCH/REPLACE blocks sequentially."""
    blocks = parse_search_replace_blocks(patch)
    if not blocks:
        raise PatchError("Invalid search/replace format (need SEARCH: ... REPLACE: ...)")
    text = original
    for search, replace in blocks:
        text = _apply_one_search_replace(text, search, replace)
    return text


def parse_search_replace_blocks(patch: str) -> list[tuple[str, str]]:
    """Parse ``SEARCH:`` / ``REPLACE:`` blocks from a patch string."""
    if "SEARCH:" not in patch or "REPLACE:" not in patch:
        return []

    blocks: list[tuple[str, str]] = []
    rest = patch
    while True:
        s_idx = rest.find("SEARCH:")
        if s_idx == -1:
            break
        rest = rest[s_idx + len("SEARCH:") :]
        if rest.startswith("\n"):
            rest = rest[1:]
        r_idx = rest.find("REPLACE:")
        if r_idx == -1:
            raise PatchError("SEARCH: without matching REPLACE:")
        search = rest[:r_idx]
        rest = rest[r_idx + len("REPLACE:") :]
        if rest.startswith("\n"):
            rest = rest[1:]
        next_s = rest.find("\nSEARCH:")
        next_s_bol = rest.find("SEARCH:")
        # A following block starts at a line beginning with SEARCH:, or at
        # SEARCH: immediately after a newline we already kept in replace.
        cut: int | None
        if next_s != -1:
            cut = next_s + 1  # keep the newline out of replace; leave SEARCH:
        elif next_s_bol == 0:
            cut = 0
        else:
            cut = None
        if cut is None:
            replace = rest
            rest = ""
        else:
            replace = rest[:cut]
            rest = rest[cut:]
        if search.endswith("\n"):
            search = search[:-1]
        if replace.endswith("\n"):
            replace = replace[:-1]
        blocks.append((search, replace))
    return blocks


def _apply_one_search_replace(original: str, search: str, replace: str) -> str:
    if search == "":
        raise PatchError("Empty SEARCH block")

    count = original.count(search)
    if count == 1:
        return original.replace(search, replace, 1)
    if count > 1:
        raise PatchError(
            f"Search string found {count} times; provide more surrounding context "
            "to disambiguate"
        )

    span = _flexible_find(original, search)
    if span is None:
        raise PatchError("Search string not found")
    start, end = span
    return original[:start] + replace + original[end:]


def _flexible_find(original: str, search: str) -> tuple[int, int] | None:
    """Locate ``search`` allowing trailing-whitespace or indent differences.

    Matches whole lines only. Raises PatchError if the flexible match is
    ambiguous.
    """
    orig_lines = original.splitlines(keepends=True)
    search_rows = search.splitlines()
    n = len(search_rows)
    if n == 0:
        return None

    def _span(i: int) -> tuple[int, int]:
        start = sum(len(orig_lines[j]) for j in range(i))
        end = start + sum(len(orig_lines[j]) for j in range(i, i + n))
        return start, end

    orig_plain = [ln.rstrip("\r\n") for ln in orig_lines]
    orig_rstrip = [ln.rstrip() for ln in orig_plain]
    search_rstrip = [ln.rstrip() for ln in search_rows]

    matches = [
        i
        for i in range(0, len(orig_plain) - n + 1)
        if orig_rstrip[i : i + n] == search_rstrip
    ]
    if len(matches) == 1:
        return _span(matches[0])
    if len(matches) > 1:
        raise PatchError(
            f"Search string found {len(matches)} times (whitespace-flexible); "
            "provide more context"
        )

    orig_strip = [ln.strip() for ln in orig_plain]
    search_strip = [ln.strip() for ln in search_rows]
    if search_strip == [""] * n:
        return None
    matches = [
        i
        for i in range(0, len(orig_plain) - n + 1)
        if orig_strip[i : i + n] == search_strip
    ]
    if len(matches) == 1:
        return _span(matches[0])
    if len(matches) > 1:
        raise PatchError(
            f"Search string found {len(matches)} times (indent-flexible); "
            "provide more context"
        )
    return None


def parse_hunks(patch: str) -> list[Hunk]:
    """Parse unified-diff hunks from ``patch``.

    Raises PatchError if a hunk header or body line is malformed, or if no
    hunks are present.
    """
    hunks: list[Hunk] = []
    lines = patch.splitlines()
    i = 0
    while i < len(lines):
        header = lines[i]
        match = HUNK_HEADER.match(header)
        if not match:
            if header.startswith("@@"):
                raise PatchError(f"Malformed hunk header: {header}")
            i += 1
            continue
        old_start = int(match.group(1))
        old_count = int(match.group(2)) if match.group(2) is not None else 1
        new_start = int(match.group(3))
        new_count = int(match.group(4)) if match.group(4) is not None else 1
        i += 1
        body: list[str] = []
        while i < len(lines):
            line = lines[i]
            if line.startswith("@@"):
                break
            if line.startswith("diff "):
                break
            if line.startswith("---") or line.startswith("+++"):
                i += 1
                continue
            if line.startswith("\\"):
                i += 1
                continue
            if line == "":
                body.append(" ")
                i += 1
                continue
            tag = line[0]
            if tag not in (" ", "+", "-"):
                raise PatchError(
                    f"Malformed hunk line (expected ' ', '+', or '-'): {line!r}"
                )
            body.append(line)
            i += 1
        hunks.append(
            Hunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                lines=body,
            )
        )
    if not hunks:
        raise PatchError("No hunks found in unified diff")
    return hunks


def apply_unified_diff(original: str, patch: str) -> str:
    """Apply a unified diff to ``original``, matching hunks by content."""
    original_lines = original.splitlines()
    had_trailing_newline = original.endswith("\n") if original else False
    hunks = parse_hunks(patch)

    result = original_lines[:]
    # Apply bottom-to-top so earlier hunks' hinted line numbers stay valid
    # when we fall back to them.
    for hunk in sorted(hunks, key=lambda h: h.old_start, reverse=True):
        old_block = [ln[1:] for ln in hunk.lines if ln[:1] in (" ", "-")]
        new_block = [ln[1:] for ln in hunk.lines if ln[:1] in (" ", "+")]
        pos = _locate_old_block(result, old_block, hunk.old_start)
        if pos is None:
            expected = "\n".join(old_block) if old_block else "(empty insertion point)"
            raise PatchError(
                f"Hunk does not match file content "
                f"(@@ -{hunk.old_start},{hunk.old_count} "
                f"+{hunk.new_start},{hunk.new_count} @@).\n"
                f"Expected to find:\n{expected}"
            )
        start, end = pos
        result[start:end] = new_block

    text = "\n".join(result)
    if had_trailing_newline:
        if text and not text.endswith("\n"):
            text += "\n"
        elif not text:
            text = "\n" if original == "\n" else ""
    elif original == "" and result:
        text += "\n"
    return text


def _locate_old_block(
    lines: list[str], old_block: list[str], old_start: int
) -> tuple[int, int] | None:
    """Return ``[start, end)`` in ``lines`` corresponding to ``old_block``.

    ``old_start`` is the 1-based unified-diff line number. An empty old block
    is an insertion: ``old_start == 0`` means the beginning of the file,
    otherwise the insertion is after that (1-based) line.
    """
    n = len(old_block)
    if n == 0:
        if old_start <= 0:
            return 0, 0
        idx = min(old_start, len(lines))
        return idx, idx

    hint = max(old_start - 1, 0)
    if hint + n <= len(lines) and lines[hint : hint + n] == old_block:
        return hint, hint + n

    matches = [
        i for i in range(0, len(lines) - n + 1) if lines[i : i + n] == old_block
    ]
    if len(matches) == 1:
        return matches[0], matches[0] + n
    if len(matches) > 1:
        best = min(matches, key=lambda i: abs(i - hint))
        return best, best + n

    stripped_old = [ln.rstrip() for ln in old_block]
    matches = [
        i
        for i in range(0, len(lines) - n + 1)
        if [ln.rstrip() for ln in lines[i : i + n]] == stripped_old
    ]
    if len(matches) == 1:
        return matches[0], matches[0] + n
    if len(matches) > 1:
        best = min(matches, key=lambda i: abs(i - hint))
        return best, best + n
    return None
