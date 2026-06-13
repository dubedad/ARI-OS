"""ar.t4 embedding tests — embed(), similarity, all three backends.

Verifies the public, scrubbed port of the heavy brain's embedding spine:
- ``off`` returns ``None`` per text and does not touch the network.
- ``ollama`` goes through :class:`EmbedClient`, recovers from transient 5xx
  and dim-0 (retry + backoff), and shrinks oversized inputs (size-cap).
- ``api`` uses the ask.get_key plumbing; the network call is injected so the
  test never reaches a real provider.
- ``cosine`` is correct on known vectors and on zero-length inputs.
- :class:`CosineScorer` returns the max overlap and ``0.0`` on empty inputs.

These cover DoD-4 (embeddings wired) and DoD-7 (retrieval works with no
embedding server).
"""
from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import httpx
import pytest

from ari_os.tools.cortex import db, embed
from ari_os.tools.cortex.embed import (
    API_DEFAULT_MODEL,
    EMBED_DIM,
    EmbedClient,
    EmbedError,
    pack_embedding,
    unpack_embedding,
)
from ari_os.tools.cortex.similarity import CosineScorer, cosine


# ---------- helpers --------------------------------------------------------

def _ok_response(dim: int = EMBED_DIM) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = 200
    r.json.return_value = {"embedding": [0.1] * dim}
    r.raise_for_status = MagicMock()
    return r


def _500_response() -> httpx.Response:
    return httpx.Response(status_code=500, request=httpx.Request("POST", "http://test"))


def _size_error() -> httpx.HTTPStatusError:
    resp = httpx.Response(
        status_code=500,
        text='{"error":"the input length exceeds the context length"}',
        request=httpx.Request("POST", "http://test"),
    )
    return httpx.HTTPStatusError("500", request=resp.request, response=resp)


# ---------- cosine + CosineScorer (port of source tests) -------------------

def test_cosine_basic():
    assert cosine([1, 0, 0], [1, 0, 0]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([0, 0], [1, 1]) == 0.0          # zero-vector guard


def test_cosine_zero_a():
    assert cosine([0, 0, 0], [1, 2, 3]) == 0.0


def test_cosine_known_value():
    # 45° between (1,1) and (1,0)
    assert math.isclose(cosine([1, 1], [1, 0]), 1.0 / math.sqrt(2), rel_tol=1e-9)


def test_cosine_scorer_overlap_is_max_over_response():
    s = CosineScorer()
    chunk = [1.0, 0.0, 0.0]
    responses = [[0.0, 1.0, 0.0], [0.9, 0.1, 0.0]]   # 2nd is close
    ov = s.overlap(chunk, responses)
    assert math.isclose(ov, cosine(chunk, responses[1]), rel_tol=1e-9)
    assert s.overlap(chunk, []) == 0.0


# ---------- embed(): off backend --------------------------------------------

def test_embed_off_returns_none_per_text():
    out = embed.embed(["hello", "world"], backend="off")
    assert out == [None, None]


def test_embed_off_never_touches_network():
    """``off`` must not import / call any embed client."""
    with patch("ari_os.tools.cortex.embed.EmbedClient") as MockClient:
        out = embed.embed(["a", "b", "c"], backend="off")
        MockClient.assert_not_called()
    assert out == [None, None, None]


def test_off_backend_lets_lexical_retrieval_still_work(tmp_path):
    """DoD-7: retrieval is functional with ``off`` embeddings (FTS5 only)."""
    db_path = tmp_path / "brain.db"
    db.init_db(db_path)
    con = db.connect(db_path)
    try:
        # Insert a source + chunk directly (lexical path doesn't need vectors).
        con.execute(
            "INSERT INTO source(path, layer, mtime, sha256, last_indexed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("remember:t1", "semantic", 0, "x" * 64, 0),
        )
        sid = con.execute(
            "SELECT id FROM source WHERE path=?", ("remember:t1",)
        ).fetchone()[0]
        con.execute(
            "INSERT INTO chunk(source_id, ordinal, text, line_start, line_end, "
            "region, distillation_tier) VALUES (?, 0, ?, 1, 1, 'wernicke', 0)",
            (sid, "monotropic focus on a single integration thread"),
        )
        # FTS lookup using the same text the chunker would have produced.
        rows = con.execute(
            "SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ?",
            ("monotropic",),
        ).fetchall()
    finally:
        con.close()
    assert rows, "FTS5 lexical retrieval must work with no embedding server"
    # And embed() with off must yield None for these texts.
    out = embed.embed(["monotropic focus on a single integration thread"],
                      backend="off")
    assert out == [None]


# ---------- embed(): ollama backend -----------------------------------------

def test_embed_ollama_dispatches_to_embed_client():
    fake_client = MagicMock()
    fake_client.embed.return_value = [[0.0] * EMBED_DIM, [0.1] * EMBED_DIM]
    out = embed.embed(["a", "b"], backend="ollama", embed_client=fake_client)
    fake_client.embed.assert_called_once_with(["a", "b"])
    assert out == [[0.0] * EMBED_DIM, [0.1] * EMBED_DIM]


def test_embed_ollama_constructs_default_client():
    """When no embed_client is passed, ``ollama`` builds an EmbedClient."""
    with patch("ari_os.tools.cortex.embed.EmbedClient") as MockClient:
        mock_inst = MagicMock()
        mock_inst.embed.return_value = [[0.5] * EMBED_DIM]
        MockClient.return_value = mock_inst
        out = embed.embed(["x"], backend="ollama",
                          model="m", dim=EMBED_DIM, url="http://u")
        MockClient.assert_called_once_with(model="m", dim=EMBED_DIM, url="http://u")
        mock_inst.embed.assert_called_once_with(["x"])
    assert out == [[0.5] * EMBED_DIM]


# ---------- embed(): ollama via real EmbedClient (retry + size cap) ---------

class TestRetryOn500:
    def test_recovers_after_one_500(self):
        client = EmbedClient(url="http://test", max_retries=3,
                              backoff_base=0.0, inter_request_delay=0.0)
        with patch("ari_os.tools.cortex.embed.httpx.post", side_effect=[
            httpx.HTTPStatusError("500", request=httpx.Request("POST", "http://test"),
                                  response=_500_response()),
            _ok_response(),
        ]):
            out = client.embed(["hello"])
        assert len(out) == 1
        assert len(out[0]) == EMBED_DIM

    def test_exhausts_retries_raises(self):
        client = EmbedClient(url="http://test", max_retries=2,
                              backoff_base=0.0, inter_request_delay=0.0)
        err = httpx.HTTPStatusError("500", request=httpx.Request("POST", "http://test"),
                                    response=_500_response())
        with patch("ari_os.tools.cortex.embed.httpx.post", side_effect=[err, err]):
            with pytest.raises(EmbedError, match="Ollama embed call failed"):
                client.embed(["hello"])

    def test_no_retry_on_4xx(self):
        client = EmbedClient(url="http://test", max_retries=3,
                              backoff_base=0.0, inter_request_delay=0.0)
        r400 = httpx.Response(status_code=400, request=httpx.Request("POST", "http://test"))
        err = httpx.HTTPStatusError("400", request=httpx.Request("POST", "http://test"),
                                    response=r400)
        with patch("ari_os.tools.cortex.embed.httpx.post", side_effect=err):
            with pytest.raises(EmbedError):
                client.embed(["hello"])


class TestRetryOnDim0:
    def test_recovers_after_dim0(self):
        client = EmbedClient(url="http://test", max_retries=3,
                              backoff_base=0.0, inter_request_delay=0.0)
        empty_resp = MagicMock(spec=httpx.Response)
        empty_resp.status_code = 200
        empty_resp.json.return_value = {"embedding": []}
        empty_resp.raise_for_status = MagicMock()
        with patch("ari_os.tools.cortex.embed.httpx.post",
                   side_effect=[empty_resp, _ok_response()]):
            out = client.embed(["hello"])
        assert out and len(out[0]) == EMBED_DIM

    def test_wrong_dim_nonzero_no_retry(self):
        client = EmbedClient(url="http://test", max_retries=3,
                              backoff_base=0.0, inter_request_delay=0.0)
        bad = MagicMock(spec=httpx.Response)
        bad.status_code = 200
        bad.json.return_value = {"embedding": [0.1] * 100}
        bad.raise_for_status = MagicMock()
        with patch("ari_os.tools.cortex.embed.httpx.post", return_value=bad):
            with pytest.raises(EmbedError, match="Wrong model"):
                client.embed(["hello"])


class TestSizeCap:
    def test_size_error_truncates_then_succeeds(self):
        client = EmbedClient(url="http://test", max_retries=3,
                              backoff_base=0.0, inter_request_delay=0.0)
        with patch("ari_os.tools.cortex.embed.httpx.post",
                   side_effect=[_size_error(), _ok_response()]):
            out = client.embed(["x" * 50000])
        assert len(out) == 1 and len(out[0]) == EMBED_DIM

    def test_truncation_actually_shrinks_payload(self):
        sent: list[int] = []

        def fake_post(url, json, timeout):
            sent.append(len(json["prompt"]))
            if len(json["prompt"]) > 4000:
                raise _size_error()
            return _ok_response()

        client = EmbedClient(url="http://test", max_retries=3,
                              backoff_base=0.0, inter_request_delay=0.0)
        with patch("ari_os.tools.cortex.embed.httpx.post", side_effect=fake_post):
            client.embed(["a" * 60000])
        assert sent[0] > sent[-1]
        assert sent[-1] <= 4000

    def test_converges_for_arbitrarily_large_input(self):
        def fake_post(url, json, timeout):
            if len(json["prompt"]) > 2000:
                raise _size_error()
            return _ok_response()

        client = EmbedClient(url="http://test", max_retries=3,
                              backoff_base=0.0, inter_request_delay=0.0)
        with patch("ari_os.tools.cortex.embed.httpx.post", side_effect=fake_post):
            out = client.embed(["a" * 1_000_000])
        assert out and len(out[0]) == EMBED_DIM


# ---------- embed(): api backend --------------------------------------------

def test_embed_api_uses_injected_call():
    """The ``api_call`` injection seam is the test entry point — the real
    network call goes through ask.get_key + httpx but we never reach it."""
    calls: list[tuple[str, str, int, float]] = []

    def fake_api_call(text, model, dim, timeout):
        calls.append((text, model, dim, timeout))
        return [0.7] * dim

    out = embed.embed(["hello", "world"], backend="api",
                      api_call=fake_api_call, model=API_DEFAULT_MODEL)
    assert len(out) == 2
    assert all(v is not None and len(v) == EMBED_DIM for v in out)
    assert [c[0] for c in calls] == ["hello", "world"]
    assert all(c[1] == API_DEFAULT_MODEL for c in calls)
    assert all(c[2] == EMBED_DIM for c in calls)


def test_embed_api_wrong_dim_raises_via_injection(monkeypatch):
    """If the api returns the wrong dimensionality, embed() surfaces EmbedError."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-doesnt-matter")

    def bad_api_call(text, model, dim, timeout):
        return [0.0] * (dim + 1)

    with pytest.raises(EmbedError, match="dim"):
        embed.embed(["x"], backend="api", api_call=bad_api_call)


def test_embed_api_no_key_exits_cleanly(monkeypatch):
    """No key in env and keychain lookup is forced to fail — the real
    backend path (without injection) must surface a clear failure."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # Force the keychain lookup to fail so the function bails.
    with patch("ari_os.tools.ask.get_key",
               side_effect=SystemExit("Missing key for google")):
        with pytest.raises(SystemExit):
            embed.embed(["x"], backend="api", model="text-embedding-004")


# ---------- pack / unpack ---------------------------------------------------

def test_pack_unpack_roundtrip():
    vec = [float(i) / 100 for i in range(EMBED_DIM)]
    raw = pack_embedding(vec)
    assert len(raw) == EMBED_DIM * 4
    assert unpack_embedding(raw) == pytest.approx(vec)


def test_pack_rejects_wrong_dim():
    with pytest.raises(ValueError, match="768-d"):
        pack_embedding([0.0] * 100)


# ---------- unknown backend -------------------------------------------------

def test_embed_unknown_backend_raises():
    with pytest.raises(EmbedError, match="unknown embed backend"):
        embed.embed(["x"], backend="nonsense")
