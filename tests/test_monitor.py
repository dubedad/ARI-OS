from ari_os.tools import monitor


def test_render_lists_workers_and_status():
    state = {"workers": [
        {"id": "w-1-impl", "label": "impl", "status": "running"},
        {"id": "w-2-fix", "label": "fix", "status": "blocked"},
        {"id": "w-3-do", "label": "do", "status": "done"}],
        "questions": ["w-2-fix"]}
    html = monitor.render_html(state)
    assert "impl" in html and "fix" in html and "do" in html
    assert "running" in html and "blocked" in html and "done" in html
    # System 7 aesthetic markers present
    assert "Chicago" in html or "system-ui" in html
    assert "title-bar" in html
    # question surfaced
    assert "w-2-fix" in html


def test_render_handles_empty():
    html = monitor.render_html({"workers": [], "questions": []})
    assert "<html" in html.lower()
    assert "ARI-OS" in html


def test_themes_share_stipple_style_but_differ_in_palette():
    beige = monitor.body_background("beige")
    stipple = monitor.body_background("stipple")
    assert beige != stipple
    # both use the System 7 stipple style
    assert "radial-gradient" in beige and "radial-gradient" in stipple
    assert "background-size:4px 4px" in beige and "background-size:4px 4px" in stipple
    # fill layer must not tile (only the stipple repeats)
    assert "no-repeat" in beige and "no-repeat" in stipple
    # stipple carries the lavender->pink palette
    assert "#C8A8E9" in stipple and "#F2B8DC" in stipple


def test_unknown_theme_falls_back_to_default():
    assert monitor.body_background("nope") == monitor.body_background(monitor.DEFAULT_THEME)


def test_render_honors_explicit_theme():
    html = monitor.render_html({"workers": [], "questions": []}, theme="stipple")
    assert "#C8A8E9" in html


def test_render_includes_gradient_color_picker():
    html = monitor.render_html({"workers": [], "questions": []})
    assert 'type="color"' in html        # picker present
    assert "localStorage" in html        # choice persists across refresh
    assert "linear-gradient" in html     # recolors the dithered gradient
