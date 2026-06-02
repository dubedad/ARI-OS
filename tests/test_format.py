import pytest
from ari_os.tools import format as fmt


def test_marker_returns_canonical_strings():
    assert fmt.marker("action") == "→ ACTION"
    assert fmt.marker("decision") == "→ DECISION"
    assert fmt.marker("question") == "→ QUESTION"
    assert fmt.marker("none") == "→ NO DECISION NEEDED"


def test_marker_unknown_raises():
    with pytest.raises(ValueError):
        fmt.marker("bogus")


def test_with_marker_appends_bold_block_on_its_own_line():
    out = fmt.with_marker("Here is the status.", "decision")
    lines = out.splitlines()
    assert lines[0] == "Here is the status."
    assert lines[-1] == "**→ DECISION**"
    assert "" in lines  # blank separator line present


def test_summary_box_is_closed_and_legend_is_beneath():
    out = fmt.summary_box("STATUS", ["branch main", "tests pass"],
                          paths=["/work/proj/file.py"])
    box_part, _, legend = out.partition("\n\n")
    box_lines = box_part.splitlines()
    assert box_lines[0].startswith("┌") and box_lines[0].endswith("┐")
    assert box_lines[-1].startswith("└") and box_lines[-1].endswith("┘")
    # path appears only in the legend, never inside the box
    assert "/work/proj/file.py" not in box_part
    assert "/work/proj/file.py" in legend
    assert legend.strip().startswith("1.")


def test_summary_box_without_paths_has_no_legend():
    out = fmt.summary_box("S", ["a"])
    assert "\n\n" not in out  # box only
