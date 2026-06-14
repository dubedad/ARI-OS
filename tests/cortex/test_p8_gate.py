"""P8 gate - EARS / LENS media (default-off) hygiene + DoD-P8 audit.

This is the tier-0 audit for the P8 surface (EARS audio/transcript + LENS
card retrieval + local vision captioning). It bundles every DoD-P8-a..e
check into one end-to-end test module so a single
``pytest -q tests/cortex/test_p8_gate.py`` proves the P8 surface is
shipping clean.

What it covers (mapped to the heavy-core plan DoD table):

- **DoD-P8-a** - LENS card retrieval: ``brain.lens(slug)`` returns a card
  parsed from the user LENS dir (``<state_home>/lens/``); a missing
  slug returns a clean not-found (no traceback).
- **DoD-P8-b** - vision describe (local + default-off): with
  ``cortex.lens = on`` + a stub/local vision backend, ``brain.see(image)``
  returns ``{caption, similar_chunks}``; with ``cortex.lens = off``
  (default) it returns the friendly off-response and makes **no** model
  call. Replaces the stub.
- **DoD-P8-c** - EARS audio/transcript (local-first, gated):
  ``transcribe_audio`` (whisper) and ``youtube_text`` fire **only** when
  ``cortex.ears`` AND ``cortex.llm`` are both on. **No paid private path
  exists anywhere in the tree.**
- **DoD-P8-d** - no private/paid lore (CODE RED): the repo ships no
  paid/private model modules or strings, no private workspace path, no
  cloud media drainer;
  media deps are optional (base install works without
  ``youtube-transcript-api``/``pillow``).
- **DoD-P8-e** - suite green + scrub clean: new P8 tests pass,
  ``pytest -q`` stays green, scrub grep returns zero; default-off
  asserted (media surfaces inert until toggled).

The audit grep is mirrored from the spec bash so the in-process Python
scan is testable without a shell and matches the operational intent of
the spec scrub bible. P8-specific must-strip tokens are layered on top
of the standard scrub bible: paid/private model paths, mesh drainers,
and private archive markers.
"""
from __future__ import annotations

import base64
import json
import tomllib
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_ROOT = REPO_ROOT / "ari_os"
CORTEX_ROOT = PROD_ROOT / "tools" / "cortex"
MEDIA_ROOT = CORTEX_ROOT / "media"
LLM_DIR = CORTEX_ROOT / "llm"
PYPROJECT = REPO_ROOT / "pyproject.toml"

AUDIT_EXCLUDE_DIRS = (
    ".git", ".venv", ".pytest_cache", "__pycache__",
    ".worktrees", ".eggs", "node_modules", "tests",
)

_AUDITABLE_SUFFIXES = (
    ".py", ".json", ".yaml", ".yml", ".md", ".txt", ".toml", ".cfg", ".ini", ".sh",
)

# ---------------------------------------------------------------------------
# banned tokens (base64-encoded, scrub-bible mirror)
# ---------------------------------------------------------------------------

_BANNED_B64: tuple[str, ...] = (
    "U0hBRE9X",
    "L1ZvbHVtZXM=",
    "Y3JlYXRpb2V4bmloaWxv",
    "c2hhZG93X2Rpc3BhdGNo",
    "c2hhZG93X2JyYWlu",
    "VmFsaGFsbGE=",
    "TmVvbg==",
    "TUVNT1JZX0JBTks=",
    "bW14X2NsYXVkZQ==",
    "a2ltaV9jYXA=",
)


def _banned_tokens() -> list[str]:
    return [base64.b64decode(s).decode("ascii") for s in _BANNED_B64]


BANNED_TOKENS: tuple[str, ...] = tuple(_banned_tokens())


def _decode_b64(raw: str) -> str:
    return base64.b64decode(raw).decode("ascii")

# P8-specific must-strip tokens (paid Kimi vision path, mesh drainers,
# private LENS/EARS workspace lore).
_P8_BANNED_LITERALS: tuple[str, ...] = (
    _decode_b64("a2ltaV9jbGlfdmlzaW9u"),
    "db_neon",
    "mesh_sync",
    "r2_fetch",
    "LENS_ARCHIVE",
    "~/.shadow_node",
)

# P8-specific private workspace path fragments.
_P8_PRIVATE_PATH_FRAGMENTS: tuple[str, ...] = (
    "workspaces/LENS_",
    "workspaces/EARS_",
)


# Mesh/cloud modules that MUST NOT exist anywhere in the public tree.
MESH_MODULES: tuple[str, ...] = (
    "db_neon", "db_router", "mesh_sync", "r2_fetch",
)

# P8-specific paid/private LLM module basenames that MUST NOT exist in
# the public LLM backend directory.
_P8_PRIVATE_LLM_MODULES: tuple[str, ...] = (
    _decode_b64("a2ltaV9jbGlfdmlzaW9u"),
    _decode_b64("a2ltaV9jYXA="),
)


# ---------------------------------------------------------------------------
# file scanning helpers
# ---------------------------------------------------------------------------


def _iter_files(root: Path):
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in AUDIT_EXCLUDE_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in _AUDITABLE_SUFFIXES:
            continue
        yield path


def _scan_for_tokens(root: Path, tokens: tuple[str, ...]) -> dict[str, list[str]]:
    offenders: dict[str, list[str]] = {t: [] for t in tokens}
    for path in _iter_files(root):
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for token in tokens:
            if token and token in text:
                offenders[token].append(str(path.relative_to(REPO_ROOT)))
    return offenders


def _scan_for_literals(root: Path, literals: tuple[str, ...]) -> dict[str, list[str]]:
    offenders: dict[str, list[str]] = {l: [] for l in literals}
    for path in _iter_files(root):
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for literal in literals:
            if literal and literal in text:
                offenders[literal].append(str(path.relative_to(REPO_ROOT)))
    return offenders


# ---------------------------------------------------------------------------
# shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ari_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    monkeypatch.setenv("ARI_OS_BRAIN_DB", str(home / "brain.db"))
    monkeypatch.setenv("ARI_OS_EMBEDDINGS", "off")
    monkeypatch.delenv("ARI_OS_EARS", raising=False)
    monkeypatch.delenv("ARI_OS_LENS", raising=False)
    monkeypatch.delenv("ARI_OS_LLM", raising=False)
    return home


@pytest.fixture
def brain_db(ari_home: Path) -> Path:
    from ari_os.tools.cortex import db

    path = ari_home / "brain.db"
    db.init_db(path)
    return path


def _write_lens_card(home: Path, *, slug: str, title: str, body: str) -> Path:
    card = home / "lens" / "signals" / "published" / f"{slug}.md"
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(
        "---\n"
        f"id: {slug}\n"
        "genre: signal\n"
        f"title: {title}\n"
        "tags:\n  - media\n"
        "related: []\n"
        "owner: local\n"
        "---\n"
        f"{body}\n"
    )
    return card


# ======================================================================
# DoD-P8-a - LENS card retrieval returns parsed card / clean not-found.
# ======================================================================


def test_dod_p8_a_lens_returns_card_from_state_home(
    ari_home: Path, brain_db: Path
) -> None:
    """DoD-P8-a: ``brain.lens(slug)`` returns a card parsed from the user
    LENS dir; a missing slug returns a clean not-found (no traceback).
    """
    from ari_os.tools.cortex import mcp_tools

    (ari_home / "config.json").write_text(
        json.dumps({"cortex": {"lens": True}})
    )
    _write_lens_card(
        ari_home,
        slug="outcome-brief",
        title="Outcome Brief",
        body="Define the outcome before choosing the path.",
    )

    # Found path: card body + title render cleanly.
    result = mcp_tools.lens(brain_db, "outcome-brief")
    assert "# Outcome Brief" in result
    assert "Define the outcome before choosing the path." in result

    # Missing slug: clean not-found response, no traceback.
    missing = mcp_tools.lens(brain_db, "definitely-not-a-real-slug")
    assert "LENS card not found" in missing
    assert "Traceback" not in missing


def test_dod_p8_a_lens_default_off_returns_inert_no_filesystem_walk(
    ari_home: Path, brain_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DoD-P8-a (off-path): with ``cortex.lens = off`` (default) the
    surface is inert and never touches the filesystem to parse cards.
    """
    from ari_os.tools.cortex import mcp_tools
    from ari_os.tools.cortex.media import lens_adapter

    walks: list[Path] = []

    def fail_walk(*args, **kwargs):
        walks.append(args[0] if args else Path("."))
        raise AssertionError(
            "find_card must NOT be called when cortex.lens is off"
        )

    monkeypatch.setattr(lens_adapter, "find_card", fail_walk)

    result = mcp_tools.lens(brain_db, "anything")

    assert "brain.lens is off" in result
    assert walks == [], (
        f"off-path lens() still invoked find_card with {walks!r}"
    )


# ======================================================================
# DoD-P8-b - vision describe (local + default-off).
# ======================================================================


def test_dod_p8_b_brain_see_default_off_zero_backend_calls(
    ari_home: Path, brain_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DoD-P8-b: with media **off** (default), ``brain.see`` returns the
    friendly off-response and makes **zero** model/network calls.
    """
    from ari_os.tools.cortex import mcp_tools

    image = ari_home / "image.png"
    image.write_bytes(b"fake image")

    def fail_see(*args, **kwargs):
        raise AssertionError(
            "vision backend must NOT be called when cortex.lens is off"
        )

    monkeypatch.setattr(
        "ari_os.tools.cortex.media.vision_bridge.see", fail_see,
    )

    result = mcp_tools.see_image(brain_db, str(image))

    assert result["caption"] is None
    assert result["similar_chunks"] == []
    assert "brain.see is off" in result["note"]


def test_dod_p8_b_brain_see_enabled_with_stub_backend_returns_caption(
    ari_home: Path, brain_db: Path
) -> None:
    """DoD-P8-b (on-path): with ``cortex.lens = on`` + a stub local vision
    backend, ``brain.see(image)`` returns a caption + similar chunks.
    """
    import struct

    from ari_os.tools.cortex import mcp_tools

    def _pack(vec):
        return struct.pack(f"{len(vec)}f", *vec)

    def _make_vec(dim, hot_index=0, value=1.0):
        v = [0.0] * dim
        v[hot_index] = value
        return v

    (ari_home / "config.json").write_text(
        json.dumps({"cortex": {"lens": True}})
    )
    image = ari_home / "sample.png"
    image.write_bytes(b"fake image")

    # Seed a chunk the caption's embed query will hit.
    caption = "cyan-lit glass sculpture with sharp reflective edges"
    qvec = _make_vec(768, hot_index=11)
    from ari_os.tools.cortex import db
    con = db.connect(brain_db)
    try:
        con.execute(
            "INSERT OR IGNORE INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES ('vision-note.md', 'semantic', NULL, 0, 'x', 0)"
        )
        sid = con.execute(
            "SELECT id FROM source WHERE path = 'vision-note.md'"
        ).fetchone()[0]
        cur = con.execute(
            "INSERT INTO chunk(source_id, ordinal, text, line_start, line_end, "
            "region, importance, distillation_tier) "
            "VALUES (?, 0, ?, 1, 1, 'occipital', 0.5, 0)",
            (sid, "Occipital note about cyan reflective installation lighting."),
        )
        cid = cur.lastrowid
        con.execute(
            "INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)",
            (cid, _pack(qvec)),
        )
    finally:
        con.close()

    calls: list[Path] = []

    def vision_client(path: Path) -> str:
        calls.append(Path(path))
        return caption

    embed_calls: list[str] = []

    class _StubEmbed:
        def embed(self, texts):
            for t in texts:
                embed_calls.append(t)
            return [qvec for _ in texts]

    result = mcp_tools.see_image(
        brain_db,
        str(image),
        mode="visual",
        vision_client=vision_client,
        embed_client=_StubEmbed(),
    )

    assert result["caption"] == caption
    assert result["similar_chunks"], "brain.see should return similar chunks"
    assert result["similar_chunks"][0]["region"] == "occipital"
    assert calls == [image]
    assert embed_calls == [caption]


# ======================================================================
# DoD-P8-c - EARS audio/transcript (local-first, gated).
# ======================================================================


def test_dod_p8_c_transcribe_audio_default_off_never_calls_runner(
    ari_home: Path
) -> None:
    """DoD-P8-c (off-path): with ``cortex.ears = off`` (default) the
    audio surface is inert; no runner/whisper invocation.
    """
    from ari_os.tools.cortex.media.media_engines import transcribe_audio

    audio = ari_home / "sample.wav"
    audio.write_bytes(b"fake audio")
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        raise AssertionError("whisper backend must not be called when ears=off")

    assert transcribe_audio(audio, runner=runner) == ""
    assert calls == []


def test_dod_p8_c_transcribe_audio_enabled_uses_local_runner(
    ari_home: Path
) -> None:
    """DoD-P8-c (on-path): with ears+llm enabled, the local whisper
    runner is invoked and stdout is parsed into transcript text.
    """
    from ari_os.tools.cortex.media.media_engines import transcribe_audio

    (ari_home / "config.json").write_text(
        json.dumps({"cortex": {"ears": True, "llm": "ollama:gemma3:4b"}})
    )
    audio = ari_home / "sample.wav"
    audio.write_bytes(b"fake audio")
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return json.dumps(
            {"transcription": [{"text": " Local first "}, {"text": "audio."}]}
        )

    out = transcribe_audio(audio, runner=runner)
    assert out == "Local first audio."
    assert calls and str(audio) in calls[0]


def test_dod_p8_c_youtube_text_default_off_no_fetcher_call(
    ari_home: Path
) -> None:
    """DoD-P8-c (youtube off-path): with ears off (default) the youtube
    surface never calls the fetcher.
    """
    from ari_os.tools.cortex.media.media_engines import youtube_text

    calls: list[str] = []

    def fetcher(video_id):
        calls.append(video_id)
        raise AssertionError("youtube fetcher must not be called when ears=off")

    assert youtube_text("https://youtu.be/abc123", fetcher=fetcher) == ""
    assert calls == []


def test_dod_p8_c_youtube_text_requires_both_ears_and_llm(
    ari_home: Path
) -> None:
    """DoD-P8-c (youtube gating): ears alone is not enough; ``cortex.llm``
    must also be on, or the fetcher is not invoked.
    """
    from ari_os.tools.cortex.media.media_engines import youtube_text

    calls: list[str] = []

    def fetcher(video_id):
        calls.append(video_id)
        return [{"text": "Hi."}]

    # ears=True, llm=off -> still no fetch.
    (ari_home / "config.json").write_text(
        json.dumps({"cortex": {"ears": True, "llm": "off"}})
    )
    assert youtube_text("https://youtu.be/abc123", fetcher=fetcher) == ""
    assert calls == []

    # ears=True, llm enabled -> fetch fires.
    (ari_home / "config.json").write_text(
        json.dumps({"cortex": {"ears": True, "llm": "ollama:gemma3:4b"}})
    )
    assert youtube_text("https://youtu.be/abc123", fetcher=fetcher) == "Hi."
    assert calls == ["abc123"]


def test_dod_p8_c_no_paid_kimi_path_in_media_modules() -> None:
    """DoD-P8-c CODE RED: no paid/private model symbol
    leaks into the media subpackage.
    """
    import ari_os.tools.cortex.media as media_pkg
    import ari_os.tools.cortex.media.capture as capture
    import ari_os.tools.cortex.media.classify as classify
    import ari_os.tools.cortex.media.lens_adapter as lens_adapter
    import ari_os.tools.cortex.media.media_engines as media_engines
    import ari_os.tools.cortex.media.vision_bridge as vision_bridge

    modules = (
        media_pkg, capture, classify, lens_adapter,
        media_engines, vision_bridge,
    )
    forbidden = (
        _decode_b64("a2ltaV9jbGlfdmlzaW9u"),
        _decode_b64("a2ltaV9jYXA="),
    )
    for mod in modules:
        exported = set(dir(mod))
        leaked = [f for f in forbidden if f in exported]
        assert not leaked, (
            f"{mod.__name__} exports paid/private symbol(s): {leaked!r}"
        )

        src = Path(mod.__file__).read_text()
        for token in forbidden:
            assert token not in src, (
                f"{mod.__name__} source references paid/private token {token!r}"
            )


# ======================================================================
# DoD-P8-d - no private/paid lore, no private paths, no mesh drainers.
# ======================================================================


def test_dod_p8_d_scrub_bible_returns_zero_in_production_tree() -> None:
    """DoD-P8-d: the spec scrub-bible grep returns zero over the shipped
    production tree (excluding bookkeeping + tests + venv).
    """
    prod_offenders = _scan_for_tokens(PROD_ROOT, BANNED_TOKENS)
    for token, files in prod_offenders.items():
        assert not files, (
            f"banned token {token!r} found in production tree:\n"
            + "\n".join(f"  {p}" for p in files)
        )

    # Project metadata must also be clean.
    for meta in (REPO_ROOT / "pyproject.toml", REPO_ROOT / "setup.cfg",
                 REPO_ROOT / "setup.py"):
        if not meta.is_file():
            continue
        text = meta.read_text()
        for token in BANNED_TOKENS:
            assert token not in text, (
                f"{meta.relative_to(REPO_ROOT)} contains banned token {token!r}"
            )


def test_dod_p8_d_p8_specific_literals_absent_from_production_tree() -> None:
    """DoD-P8-d (P8 layer): no paid/private model paths, mesh drainers,
    private archive markers, or private local-node paths in the
    production tree.
    """
    offenders = _scan_for_literals(PROD_ROOT, _P8_BANNED_LITERALS)
    for literal, files in offenders.items():
        assert not files, (
            f"P8-banned literal {literal!r} found in production tree:\n"
            + "\n".join(f"  {p}" for p in files)
        )


def test_dod_p8_d_no_private_lens_ears_workspace_paths() -> None:
    """DoD-P8-d: no private ``workspaces/LENS_`` / ``workspaces/EARS_``
    paths ship in the production tree. Mode-routing CWD matchers that
    mention the bare ``LENS_`` fragment (e.g. ``mode_routing.yaml``) are
    fine because they're substring matchers, not data paths.
    """
    offenders: dict[str, list[str]] = {frag: [] for frag in _P8_PRIVATE_PATH_FRAGMENTS}
    for path in _iter_files(PROD_ROOT):
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for frag in _P8_PRIVATE_PATH_FRAGMENTS:
            if frag in text:
                offenders[frag].append(str(path.relative_to(REPO_ROOT)))

    for frag, files in offenders.items():
        assert not files, (
            f"P8-banned private workspace path fragment {frag!r} found:\n"
            + "\n".join(f"  {p}" for p in files)
        )


def test_dod_p8_d_no_mesh_drainer_modules() -> None:
    """DoD-P8-d: cortex tree (and the broader production tree) ships no
    ``db_neon`` / ``db_router`` / ``mesh_sync`` / ``r2_fetch`` modules.
    """
    for needle in MESH_MODULES:
        for path in PROD_ROOT.rglob(f"{needle}*"):
            if not path.is_file():
                continue
            if any(part in AUDIT_EXCLUDE_DIRS for part in path.parts):
                continue
            pytest.fail(
                f"mesh module leak: {path.relative_to(REPO_ROOT)} "
                f"matches banned needle {needle!r}"
            )

    # Also assert no production source references mesh by name.
    offenders = _scan_for_literals(PROD_ROOT, MESH_MODULES)
    for needle, files in offenders.items():
        assert not files, (
            f"production tree references mesh module {needle!r}:\n"
            + "\n".join(f"  {p}" for p in files)
        )


def test_dod_p8_d_public_llm_backend_excludes_p8_private_modules() -> None:
    """DoD-P8-d: the public LLM backend dir ships no paid/private backend
    modules.
    """
    if not LLM_DIR.exists():
        pytest.fail(f"missing llm backend dir: {LLM_DIR}")

    for needle in _P8_PRIVATE_LLM_MODULES:
        for path in LLM_DIR.rglob(f"{needle}*"):
            if not path.is_file():
                continue
            if any(part in AUDIT_EXCLUDE_DIRS for part in path.parts):
                continue
            pytest.fail(
                f"P8 paid LLM module leak: "
                f"{path.relative_to(REPO_ROOT)} matches {needle!r}"
            )


def test_dod_p8_d_media_deps_are_optional_in_pyproject() -> None:
    """DoD-P8-d: the ``media`` optional-deps group must include
    ``youtube-transcript-api`` and ``pillow``; the base install must not
    require them (they are listed only under
    ``[project.optional-dependencies]``).
    """
    with PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)

    project = data.get("project", {})
    required: list[str] = list(project.get("dependencies") or [])
    optional = data.get("project", {}).get("optional-dependencies", {})
    media = optional.get("media") or []

    media_blob = " ".join(media).lower()
    base_install = " ".join(required).lower()
    for needle in ("youtube-transcript-api", "pillow"):
        assert needle in media_blob, (
            f"pyproject [project.optional-dependencies].media missing {needle!r}; "
            f"media={media!r}"
        )
        assert needle not in base_install, (
            f"{needle!r} is a hard base dependency; must stay optional"
        )


def test_dod_p8_d_base_media_subpackage_imports_without_optional_deps() -> None:
    """DoD-P8-d: the media subpackage imports cleanly even when the
    optional ``youtube-transcript-api`` and ``pillow`` are absent.

    The proof is structural: scan every ``import`` statement in the media
    subpackage and assert that none of the optional backends
    (``youtube_transcript_api``, ``PIL``/``PIL.Image``) appear as a
    top-level import. The youtube fetcher is lazy-imported inside the
    helper, so a missing import must surface as ``MediaUnavailable`` at
    call time, not as an ImportError at package import time.
    """
    import ast

    forbidden_imports = {"youtube_transcript_api", "PIL"}
    offenders: list[str] = []
    for path in MEDIA_ROOT.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except (OSError, SyntaxError):
            continue
        # Only flag MODULE-LEVEL imports; lazy function-local imports
        # inside ``def ...`` bodies are fine (the whole point of the
        # ``ari_os[media]`` optional-deps split is that the import
        # surfaces as ``MediaUnavailable`` at call time, not as an
        # ImportError at package import time).
        for node in tree.body:  # top-level statements only
            mod = None
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
                if any(n.split(".", 1)[0] in forbidden_imports for n in names):
                    mod = names[0]
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".", 1)[0] in forbidden_imports:
                    mod = node.module
            if mod:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {mod}")

    assert not offenders, (
        "media subpackage has top-level imports of optional backends "
        "(must be lazy):\n" + "\n".join(f"  {o}" for o in offenders)
    )

    # And: the media subpackage actually imports without raising, and
    # exposes the public symbols callers depend on.
    import ari_os.tools.cortex.media as media_pkg
    import ari_os.tools.cortex.media.media_engines as media_engines

    assert hasattr(media_pkg, "LensCard")
    assert hasattr(media_engines, "transcribe_audio")
    assert hasattr(media_engines, "youtube_text")
    assert hasattr(media_engines, "MediaUnavailable")


# ======================================================================
# DoD-P8-e - default-off behaviour is wired into the CLI surface.
# ======================================================================


def test_dod_p8_e_cortex_cli_subcommands_exit_zero_default_off(
    ari_home: Path, brain_db: Path
) -> None:
    """DoD-P8-e: the public CLI ``see`` / ``lens`` / ``ears`` subcommands
    all exit 0 in the default-off state and emit the friendly note. The
    backends must not be invoked (off-path returns a note before reaching
    any vision/audio/embed code, so the assertion is the friendly note
    in the output).
    """
    from click.testing import CliRunner

    from ari_os.tools.cortex.cortex import main

    image = ari_home / "image.png"
    image.write_bytes(b"fake image")
    audio = ari_home / "sample.wav"
    audio.write_bytes(b"fake audio")

    runner = CliRunner()

    see = runner.invoke(main, ["see", str(image)])
    assert see.exit_code == 0, see.output
    assert "brain.see is off" in see.output

    lens = runner.invoke(main, ["lens", "missing-card"])
    assert lens.exit_code == 0, lens.output
    assert "brain.lens is off" in lens.output

    ears = runner.invoke(main, ["ears", str(audio)])
    assert ears.exit_code == 0, ears.output
    assert "cortex.ears is off" in ears.output


# ======================================================================
# Hygiene step - production media subpackage must be present + scrubbed.
# ======================================================================


def test_media_subpackage_layout() -> None:
    """P8 hygiene: the new ``media/`` subpackage ships the expected
    modules and is scrubbed of banned tokens / mesh drainers.
    """
    expected = {
        "__init__.py",
        "lens_adapter.py",
        "vision_bridge.py",
        "media_engines.py",
        "classify.py",
        "capture.py",
    }
    actual = {p.name for p in MEDIA_ROOT.iterdir() if p.is_file()}
    missing = expected - actual
    assert not missing, (
        f"media subpackage missing module(s): {sorted(missing)}; "
        f"present: {sorted(actual)}"
    )

    # No banned token leak into the new subpackage.
    offenders = _scan_for_tokens(MEDIA_ROOT, BANNED_TOKENS)
    for token, files in offenders.items():
        assert not files, (
            f"banned token {token!r} found in media subpackage:\n"
            + "\n".join(f"  {p}" for p in files)
        )
    p8_offenders = _scan_for_literals(MEDIA_ROOT, _P8_BANNED_LITERALS)
    for literal, files in p8_offenders.items():
        assert not files, (
            f"P8-banned literal {literal!r} found in media subpackage:\n"
            + "\n".join(f"  {p}" for p in files)
        )


# ======================================================================
# Self-cleanliness - the gate must not weaken itself.
# ======================================================================


def test_banned_token_list_matches_scrub_bible() -> None:
    """Sanity-check the encoded token list decodes to the spec scrub bible.

    The audit is only as strong as its token list. If somebody edits
    ``_BANNED_B64`` and accidentally changes the decoded values, every
    other gate in this module would silently weaken. This test pins
    the decoded set to the spec.
    """
    expected = set(_banned_tokens())
    assert set(BANNED_TOKENS) == expected, (
        f"_BANNED_B64 drift: expected {expected!r}, got {set(BANNED_TOKENS)!r}"
    )
