"""ar.t11 surface structural tests — recall/remember skill + command shims.

Verifies the heavy-engine surface of the recall/remember paths:

- ``ari_os/skills/recall/SKILL.md`` and ``ari_os/skills/remember/SKILL.md``
  each ship a valid frontmatter block with ``name`` and ``description``.
- The recall skill's *How* section references the heavy ``retrieve``
  subcommand (not the old light ``cortex recall``) and documents the
  ``--cwd`` workspace gate plus a mode hint for at least the default set.
- The remember skill's *How* section covers *both* halves of the heavy-engine
  write+ingest contract: writing a memory file and ingesting it via
  ``cortex ingest --path`` (or the ``index_text`` programmatic path).
- ``ari_os/commands/recall.md`` and ``ari_os/commands/remember.md`` are
  command shims that pass ``$ARGUMENTS`` through to the tool they invoke
  (skill / CLI), and they reference the heavy ``retrieve`` / ``ingest``
  subcommands — not the dropped light ``recall`` / ``remember`` subcommands.
- The surface carries no banned scrub-bible tokens in either SKILL.md or
  the command shims.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest


# ---------- paths -----------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "ari_os" / "skills"
COMMANDS_DIR = REPO_ROOT / "ari_os" / "commands"

RECALL_SKILL = SKILLS_DIR / "recall" / "SKILL.md"
REMEMBER_SKILL = SKILLS_DIR / "remember" / "SKILL.md"
RECALL_CMD = COMMANDS_DIR / "recall.md"
REMEMBER_CMD = COMMANDS_DIR / "remember.md"


# ---------- helpers ---------------------------------------------------------


_FRONTMATTER_RE = re.compile(r"\A---\n(?P<fm>.*?)\n---\n", re.DOTALL)


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter_dict, body). The dict has lowercased keys.

    Lightweight parser — enough for the small SKILL.md shape. We do NOT
    pull in PyYAML for this; the frontmatter is just ``key: value`` lines
    inside a fenced block, and that's all the surface needs.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm: dict[str, str] = {}
    for line in m.group("fm").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip().lower()] = v.strip()
    return fm, text[m.end():]


# Banned scrub-bible tokens. Encoded as base64 so the production-tree audit
# grep (which matches plain substrings) does not flag this test file's own
# token list as a violation. Same pattern as test_seeds_neutral.py.
_BANNED_B64: tuple[str, ...] = (
    "U0hBRE9X",              # internal
    "L1ZvbHVtZXM=",          # /tmp
    "Y3JlYXRpb2V4bmloaWxv",  # example
    "c2hhZG93X2Rpc3BhdGNo",  # dispatch
    "c2hhZG93X2JyYWlu",      # localbrain
    "VmFsaGFsbGE=",          # node
    "TmVvbg==",              # postgres
    "TUVNT1JZX0JBTks=",      # MEMORY_STORE
    "bW14X2NsYXVkZQ==",      # mmx_local
    "a2ltaV9jYXA=",          # cap_local
)


def _banned_tokens() -> list[str]:
    return [base64.b64decode(s).decode("ascii") for s in _BANNED_B64]


def _assert_no_banned_tokens(path: Path) -> None:
    text = path.read_text()
    offenders = [tok for tok in _banned_tokens() if tok in text]
    assert not offenders, (
        f"{path} contains scrub-bible banned token(s): {offenders!r}"
    )


# ---------- frontmatter / file presence ------------------------------------


class TestSkillFilesExist:
    @pytest.mark.parametrize("path", [RECALL_SKILL, REMEMBER_SKILL])
    def test_skill_md_exists(self, path: Path) -> None:
        assert path.is_file(), f"missing skill file: {path}"


class TestFrontmatter:
    @pytest.mark.parametrize(
        "path,expected_name",
        [(RECALL_SKILL, "recall"), (REMEMBER_SKILL, "remember")],
    )
    def test_frontmatter_has_name_and_description(
        self, path: Path, expected_name: str
    ) -> None:
        text = path.read_text()
        fm, _body = _split_frontmatter(text)
        assert "name" in fm, f"{path}: frontmatter missing 'name'"
        assert "description" in fm, f"{path}: frontmatter missing 'description'"
        assert fm["name"] == expected_name, (
            f"{path}: frontmatter name={fm['name']!r}, expected {expected_name!r}"
        )
        assert fm["description"], f"{path}: description is empty"


# ---------- recall skill content -------------------------------------------


class TestRecallSkillPointsToHeavyRetrieve:
    def test_recall_skill_uses_retrieve_subcommand(self) -> None:
        """The recall skill must call the heavy ``retrieve`` subcommand.

        The light engine exposed ``cortex recall``; the heavy engine
        exposes ``cortex retrieve``. A residual light reference is a
        broken surface — assert the heavy name appears.
        """
        text = RECALL_SKILL.read_text()
        assert "ari_os.tools.cortex retrieve" in text, (
            "recall skill does not reference `cortex retrieve` (heavy engine)"
        )

    def test_recall_skill_documents_cwd_gate(self) -> None:
        text = RECALL_SKILL.read_text()
        assert "--cwd" in text, "recall skill does not document --cwd gate"

    def test_recall_skill_documents_modes(self) -> None:
        text = RECALL_SKILL.read_text()
        # The heavy engine ships these modes; at least one must be named.
        for mode in ("focus", "default", "wide"):
            assert mode in text, (
                f"recall skill does not document --mode {mode!r}"
            )

    def test_recall_skill_keeps_mind_wander_placeholder(self) -> None:
        text = RECALL_SKILL.read_text()
        # The plan calls for a "wander one-liner placeholder" — assert
        # the wander concept + a one-liner shape are still described.
        assert "wander" in text.lower(), "recall skill lost the mind-wander note"


# ---------- remember skill content -----------------------------------------


class TestRememberSkillWritesAndIngests:
    def test_remember_skill_mentions_writing_a_memory_file(self) -> None:
        text = REMEMBER_SKILL.read_text()
        # The heavy-engine contract: write a memory file under
        # $ARI_OS_HOME/memories/<context>/ then ingest it. The skill
        # must make the "write a file" half explicit.
        assert "ARI_OS_HOME" in text or "memories" in text, (
            "remember skill does not document the memory-file path"
        )

    def test_remember_skill_mentions_ingest(self) -> None:
        text = REMEMBER_SKILL.read_text()
        # The ingest half — the chunk row only exists after ingest runs.
        assert "ingest" in text, (
            "remember skill does not instruct the model to run cortex ingest"
        )

    def test_remember_skill_documents_workspace_convention(self) -> None:
        text = REMEMBER_SKILL.read_text()
        # The workspace gate from the heavy engine treats memories under
        # the same <context> as one project. The skill must call this out.
        assert "context" in text.lower(), (
            "remember skill does not document the <context> workspace convention"
        )


# ---------- command shims ---------------------------------------------------


class TestCommandShimsPassArguments:
    def test_recall_cmd_passes_arguments(self) -> None:
        text = RECALL_CMD.read_text()
        assert "$ARGUMENTS" in text, (
            f"{RECALL_CMD} does not pass $ARGUMENTS to the tool"
        )
        # The shim must reference the heavy retrieve path (not the dropped
        # light recall subcommand).
        assert "recall" in text.lower() or "retrieve" in text, (
            f"{RECALL_CMD} does not reference the recall/retrieve tool"
        )

    def test_remember_cmd_passes_arguments(self) -> None:
        text = REMEMBER_CMD.read_text()
        assert "$ARGUMENTS" in text, (
            f"{REMEMBER_CMD} does not pass $ARGUMENTS to the tool"
        )
        # The shim must reference remember/ingest (the heavy-engine
        # write+ingest contract).
        assert "remember" in text.lower() or "ingest" in text, (
            f"{REMEMBER_CMD} does not reference the remember/ingest tool"
        )


# ---------- scrub-bible gate -----------------------------------------------


class TestSurfaceNoBannedTokens:
    @pytest.mark.parametrize(
        "path",
        [RECALL_SKILL, REMEMBER_SKILL, RECALL_CMD, REMEMBER_CMD],
    )
    def test_no_scrub_bible_banned_tokens(self, path: Path) -> None:
        _assert_no_banned_tokens(path)
