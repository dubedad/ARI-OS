from ari_os.tools.box import render_box

def test_all_lines_equal_width_and_closed():
    out = render_box("STATUS", ["branch  main", "workers 2 running", "tests   pass"])
    lines = out.splitlines()
    widths = {len(line) for line in lines}
    assert len(widths) == 1, f"lines not equal width: {widths}"
    assert lines[0].startswith("┌") and lines[0].endswith("┐")
    assert lines[-1].startswith("└") and lines[-1].endswith("┘")
    for mid in lines[1:-1]:
        assert mid.startswith("│") and mid.endswith("│")

def test_title_appears_in_top_border():
    out = render_box("CHANGED", ["a", "b"])
    assert "CHANGED" in out.splitlines()[0]

def test_double_weight_for_alerts():
    out = render_box("→ DECISION", ["pick A or B"], weight="double")
    first = out.splitlines()[0]
    assert first.startswith("╔") and first.endswith("╗")
