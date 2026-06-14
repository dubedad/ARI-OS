"""ar.t8 surface structural tests for heavy public routines."""
from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "ari_os" / "skills"
COMMANDS_DIR = REPO_ROOT / "ari_os" / "commands"

ROUTINES = ("dream", "night", "morning")


_FRONTMATTER_RE = re.compile(r"\A---\n(?P<fm>.*?)\n---\n", re.DOTALL)


def _skill_path(name: str) -> Path:
    return SKILLS_DIR / name / "SKILL.md"


def _command_path(name: str) -> Path:
    return COMMANDS_DIR / f"{name}.md"


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm: dict[str, str] = {}
    for line in m.group("fm").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip().lower()] = value.strip()
    return fm, text[m.end():]


_SURFACE_BANNED_B64: tuple[str, ...] = (
    "U0hBRE9X",
    "UElQRUxJTkVfU1RBVEU=",
    "Q09OVEVOVF9MT0c=",
    "ZW1wb3dlcg==",
    "TWluaU1heA==",
    "cnVsZXMubWQ=",
)


def _surface_banned_tokens() -> list[str]:
    return [base64.b64decode(s).decode("ascii") for s in _SURFACE_BANNED_B64]


def _assert_no_banned_tokens(path: Path) -> None:
    text = path.read_text()
    offenders = [token for token in _surface_banned_tokens() if token in text]
    assert not offenders, f"{path} contains banned public-surface tokens: {offenders!r}"


class TestRoutineSkillFiles:
    @pytest.mark.parametrize("name", ROUTINES)
    def test_skill_file_exists(self, name: str) -> None:
        assert _skill_path(name).is_file()

    @pytest.mark.parametrize("name", ROUTINES)
    def test_skill_frontmatter_has_name_and_description(self, name: str) -> None:
        fm, _body = _split_frontmatter(_skill_path(name).read_text())
        assert fm["name"] == name
        assert fm["description"]


class TestRoutineCommandShims:
    @pytest.mark.parametrize("name", ROUTINES)
    def test_command_shim_exists(self, name: str) -> None:
        assert _command_path(name).is_file()

    @pytest.mark.parametrize("name", ROUTINES)
    def test_command_shim_invokes_matching_skill_or_tool(self, name: str) -> None:
        text = _command_path(name).read_text()
        assert "$ARGUMENTS" in text
        assert (
            f"Use the {name} skill" in text
            or f"ari_os.tools.cortex {name}" in text
        )


class TestRoutineBehaviorContracts:
    def test_dream_invokes_cortex_dream(self) -> None:
        text = _skill_path("dream").read_text()
        assert "python3 -m ari_os.tools.cortex dream" in text
        assert "consolidation" in text.lower()

    def test_night_runs_dream_before_review(self) -> None:
        text = _skill_path("night").read_text()
        body = text.split("## How", 1)[1]
        assert "python3 -m ari_os.tools.cortex dream" in text
        assert body.index("python3 -m ari_os.tools.cortex dream") < body.lower().index("review")
        assert "open" in text.lower()
        assert "near-duplicate" in text.lower()
        assert "tomorrow's focus" in text.lower()

    def test_morning_emits_maintenance_dashboard(self) -> None:
        text = _skill_path("morning").read_text()
        required = (
            "database integrity",
            "ingest freshness",
            "recent memories",
            "open threads",
            "suggestions",
        )
        missing = [phrase for phrase in required if phrase not in text.lower()]
        assert not missing


class TestRoutineSurfacesAreScrubbed:
    @pytest.mark.parametrize(
        "path",
        [
            *[_skill_path(name) for name in ROUTINES],
            *[_command_path(name) for name in ROUTINES],
        ],
    )
    def test_public_routine_surface_has_no_banned_tokens(self, path: Path) -> None:
        _assert_no_banned_tokens(path)
