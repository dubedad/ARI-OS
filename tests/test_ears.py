from ari_os.tools import cortex, ears

def test_ingest_stores_transcript_as_audio_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    conn = cortex.connect()
    mid = ears.ingest("/clips/note.m4a", context="p",
                      transcriber=lambda p: "the spoken words", conn=conn)
    assert isinstance(mid, int)
    row = conn.execute("SELECT text, source, tags FROM memory WHERE id=?", (mid,)).fetchone()
    assert row == ("the spoken words", "/clips/note.m4a", "audio")

def test_ingest_returns_none_when_no_text(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    conn = cortex.connect()
    assert ears.ingest("/clips/silent.m4a", transcriber=lambda p: None, conn=conn) is None
    assert ears.ingest("/clips/silent.m4a", transcriber=lambda p: "", conn=conn) is None
