"""Cache-stable retrieval context strata.

``ContextBlock.render()`` is the only place the four strata are
concatenated. The stable prefixes must not add render-time volatile
data such as timestamps, UUIDs, scores, counts, or query-dependent
ordering — those belong in the volatile suffix or in the user input.

Public port + scrub of the heavy brain's context block. The
``render_eternal`` / ``render_session`` helpers produce the two
cache-stable strata used by the SessionStart context emission path.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass
class ContextBlock:
    """Stratified prompt context with cache-stable prefix boundaries.

    The four strata concatenate in a fixed order: eternal, session,
    volatile, then the user input. The first two are cache-stable
    (pinned memory + active session digest); the third carries the
    query-time retrieved context; the user input is whatever the
    caller is about to ask.
    """

    eternal_prefix: str
    session_prefix: str
    volatile_suffix: str
    user_input: str = ""

    def render(self) -> str:
        """Return the exact stratum concatenation with no separator bytes."""

        return "".join(
            (
                self.eternal_prefix,
                self.session_prefix,
                self.volatile_suffix,
                self.user_input,
            )
        )

    def render_bounded(self, max_chars: int) -> str:
        """Render within ``max_chars`` by trimming only volatile tail chunks.

        The eternal and session prefixes, plus the user input, are
        load-bearing for the cache contract and CANNOT be trimmed — if
        their sum already exceeds the budget we raise rather than
        silently corrupt the cache key.
        """

        fixed = self.eternal_prefix + self.session_prefix + self.user_input
        if len(fixed) > max_chars:
            raise ValueError("Fixed ContextBlock strata exceed max_chars")

        remaining = max_chars - len(fixed)
        if len(self.volatile_suffix) <= remaining:
            return self.render()

        volatile = self._trim_volatile_tail(remaining)
        return self.eternal_prefix + self.session_prefix + volatile + self.user_input

    def fingerprint(self) -> tuple[str, str]:
        """Return hashes for eternal and eternal+session prefix stability.

        Useful for cache-key derivation and for asserting that a
        volatile-suffix change does not move the prefix fingerprints.
        """

        eternal = sha256(self.eternal_prefix.encode("utf-8")).hexdigest()
        eternal_session = sha256(
            (self.eternal_prefix + self.session_prefix).encode("utf-8")
        ).hexdigest()
        return eternal, eternal_session

    def _trim_volatile_tail(self, max_chars: int) -> str:
        if max_chars <= 0:
            return ""

        chunks = self._volatile_chunks()
        kept: list[str] = []
        used = 0
        for chunk in chunks:
            next_used = used + len(chunk)
            if next_used > max_chars:
                break
            kept.append(chunk)
            used = next_used
        return "".join(kept)

    def _volatile_chunks(self) -> list[str]:
        if not self.volatile_suffix:
            return []

        parts = self.volatile_suffix.splitlines(keepends=True)
        chunks: list[str] = []
        current: list[str] = []
        for part in parts:
            current.append(part)
            if part.strip() == "":
                chunks.append("".join(current))
                current = []
        if current:
            chunks.append("".join(current))
        return chunks


# Static header constants. Deliberately free of k=, ~tokens, mode= — the old
# emit_markdown header put per-query counts in the FIRST LINE, which busted
# the entire implicit cache every turn.
ETERNAL_HEADER = "## Brain - pinned memory (always loaded)\n\n"
SESSION_DIGEST_HEADER = "## Brain - session digests\n\n"

# Row shape shared by the fetchers in retrieve.py: (path, line_start, line_end, text)
Row = tuple[str, int, int, str]


def render_eternal(tier4_rows: list[Row]) -> str:
    """Pinned Tier-4 block. Stable sort (path, line_start); bare render — no
    scores, no counts. The header is always present so the stratum is never
    zero-length and the cache anchor never disappears."""
    parts = [ETERNAL_HEADER]
    for path, ls, le, text in sorted(tier4_rows, key=lambda r: (r[0], r[1])):
        parts.append(f"[{path}:L{ls}-L{le}]\n{text}\n\n")
    return "".join(parts)


def render_session(blackboard_md: str, digest_rows: list[Row]) -> str:
    """Blackboard + Tier-1 digests for the active workspace. Pure function of
    its inputs — mutation of the underlying data IS the cache invalidation."""
    parts: list[str] = []
    if blackboard_md:
        parts.append(blackboard_md)
        if not blackboard_md.endswith("\n"):
            parts.append("\n")
        parts.append("\n")
    if digest_rows:
        parts.append(SESSION_DIGEST_HEADER)
        for path, ls, le, text in sorted(digest_rows, key=lambda r: (r[0], r[1])):
            parts.append(f"[{path}:L{ls}-L{le}]\n{text}\n\n")
    return "".join(parts)
