import pathlib
import tomllib


REPO = pathlib.Path(__file__).resolve().parents[1]


def test_license_file_present():
    text = (REPO / "LICENSE").read_text()
    assert text.splitlines()[0] == "PolyForm Noncommercial License 1.0.0"


def test_pyproject_license_set():
    data = tomllib.loads((REPO / "pyproject.toml").read_text())
    license_value = data["project"].get("license")

    assert license_value == {"text": "PolyForm Noncommercial License 1.0.0"}
