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
