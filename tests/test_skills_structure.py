from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = sorted((ROOT / "ari_os" / "skills").glob("*/SKILL.md"))
COMMANDS = sorted((ROOT / "ari_os" / "commands").glob("*.md"))


def _frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    _, fm, _ = text.split("---", 2)
    out = {}
    for line in fm.strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def test_expected_skills_present():
    names = {p.parent.name for p in SKILLS}
    assert {"brainstorm", "handoff", "advisor", "teach"} <= names


def test_every_skill_has_frontmatter_and_h1():
    assert SKILLS, "no skills found"
    for p in SKILLS:
        text = p.read_text()
        fm = _frontmatter(text)
        assert fm.get("name"), f"{p} missing name:"
        assert fm.get("description"), f"{p} missing description:"
        assert "# " in text, f"{p} missing H1"


def test_expected_commands_present():
    names = {p.stem for p in COMMANDS}
    assert {"brainstorm", "handoff", "dispatch", "monitor"} <= names


def test_every_command_has_description_and_body():
    assert COMMANDS, "no commands found"
    for p in COMMANDS:
        text = p.read_text()
        fm = _frontmatter(text)
        assert fm.get("description"), f"{p} missing description:"
        body = text.split("---", 2)[-1].strip()
        assert body, f"{p} has empty body"
