from ari_os.tools import dispatch


def test_cmd_answer_cannot_escape_questions(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    secret = tmp_path / "secret.md"
    secret.write_text("do not touch")

    class A:
        worker_id = "../secret"
        answer = "x"

    dispatch.cmd_answer(A())
    assert secret.exists()
