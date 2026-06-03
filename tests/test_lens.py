from ari_os.tools import cortex, lens

def test_ingest_stores_caption_per_frame_as_video_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    conn = cortex.connect()
    ids = lens.ingest("/clips/demo.mp4", context="p",
                      captioner=lambda p: ["a desk", "a screen of code", ""], conn=conn)
    assert len(ids) == 2                      # empty caption skipped
    rows = conn.execute("SELECT text, tags, source FROM memory ORDER BY id").fetchall()
    assert rows == [("a desk", "video", "/clips/demo.mp4"),
                    ("a screen of code", "video", "/clips/demo.mp4")]

def test_ingest_empty_without_captioner(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    conn = cortex.connect()
    assert lens.ingest("/clips/demo.mp4", conn=conn) == []
