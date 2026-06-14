from __future__ import annotations

import json
from pathlib import Path


def _enable_ears(home: Path, *, llm: str = "ollama:gemma3:4b") -> None:
    (home / "config.json").write_text(
        json.dumps({"cortex": {"ears": True, "llm": llm}})
    )


def test_transcribe_audio_default_off_never_calls_backend(
    tmp_path: Path, monkeypatch
) -> None:
    from ari_os.tools.cortex.media.media_engines import transcribe_audio

    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"fake audio")
    calls: list[list[str]] = []

    def runner(cmd: list[str], **kwargs):
        calls.append(cmd)
        raise AssertionError("backend should not be called")

    assert transcribe_audio(audio, runner=runner) == ""
    assert calls == []


def test_transcribe_audio_enabled_uses_stub_whisper_runner(
    tmp_path: Path, monkeypatch
) -> None:
    from ari_os.tools.cortex.media.media_engines import transcribe_audio

    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    _enable_ears(home)
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"fake audio")
    calls: list[list[str]] = []

    def runner(cmd: list[str], **kwargs):
        calls.append(cmd)
        return json.dumps(
            {"transcription": [{"text": " Local first "}, {"text": "audio."}]}
        )

    assert transcribe_audio(audio, runner=runner) == "Local first audio."
    assert calls
    assert str(audio) in calls[0]


def test_youtube_text_respects_ears_and_llm_gates(
    tmp_path: Path, monkeypatch
) -> None:
    from ari_os.tools.cortex.media.media_engines import youtube_text

    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    calls: list[str] = []

    def fetcher(video_id: str):
        calls.append(video_id)
        return [{"text": "One"}, {"text": "two."}]

    assert youtube_text("https://www.youtube.com/watch?v=abc123", fetcher=fetcher) == ""
    assert calls == []

    _enable_ears(home, llm="off")
    assert youtube_text("https://youtu.be/abc123", fetcher=fetcher) == ""
    assert calls == []

    _enable_ears(home)
    assert youtube_text("https://youtu.be/abc123", fetcher=fetcher) == "One two."
    assert calls == ["abc123"]


def test_classify_routes_media_and_lens_paths() -> None:
    from ari_os.tools.cortex.media.classify import classify

    assert (
        classify(Path("captures/visual/frame.png"), configured_layer="semantic").region
        == "occipital"
    )
    assert (
        classify(Path("captures/audio/interview.wav"), configured_layer="semantic").region
        == "wernicke"
    )
    assert (
        classify(Path("lens/cards/outcome-brief.md"), configured_layer="semantic").region
        == "occipital"
    )


def test_capture_uses_local_engine_dict_without_remote_backends(tmp_path: Path) -> None:
    from ari_os.tools.cortex.media.capture import handle

    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"fake audio")
    calls: list[str] = []
    engines = {
        "transcribe_audio": lambda path: "Raw transcript from local audio.",
        "describe_image": lambda path, prompt: "Local image note.",
        "distil": lambda text: calls.append(text) or f"distilled: {text}",
        "infer_region": lambda body: "wernicke",
    }

    result = handle("audio", {}, blob_path=audio, engines=engines)

    assert result.body == "distilled: Raw transcript from local audio."
    assert result.region_hint == "wernicke"
    assert calls == ["Raw transcript from local audio."]


def test_media_modules_do_not_export_paid_or_private_symbols() -> None:
    import ari_os.tools.cortex.media.capture as capture
    import ari_os.tools.cortex.media.media_engines as media_engines

    forbidden = {
        "ki" + "mi",
        "mmx" + "_" + "claude",
        "shadow" + "_" + "brain",
    }
    exported = set(dir(media_engines)) | set(dir(capture))

    assert not (forbidden & exported)
