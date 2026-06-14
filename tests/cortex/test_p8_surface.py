from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from ari_os.tools.cortex.cortex import main


def test_media_readers_default_off_and_flip_from_env_or_config(
    tmp_path: Path, monkeypatch
) -> None:
    from ari_os.tools.cortex import config

    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    monkeypatch.delenv("ARI_OS_EARS", raising=False)
    monkeypatch.delenv("ARI_OS_LENS", raising=False)

    assert config.ears_enabled() is False
    assert config.lens_enabled() is False

    monkeypatch.setenv("ARI_OS_EARS", "on")
    monkeypatch.setenv("ARI_OS_LENS", "1")
    assert config.ears_enabled() is True
    assert config.lens_enabled() is True

    monkeypatch.delenv("ARI_OS_EARS", raising=False)
    monkeypatch.delenv("ARI_OS_LENS", raising=False)
    (home / "config.json").write_text(
        json.dumps({"cortex": {"ears": True, "lens": True}})
    )
    assert config.ears_enabled() is True
    assert config.lens_enabled() is True


def test_cortex_lens_command_exits_zero_when_default_off(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    monkeypatch.setenv("ARI_OS_BRAIN_DB", str(home / "brain.db"))

    result = CliRunner().invoke(main, ["lens", "missing-card"])

    assert result.exit_code == 0, result.output
    assert "brain.lens is off" in result.output


def test_cortex_see_default_off_prints_note_without_model_call(
    tmp_path: Path, monkeypatch
) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"fake image")
    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    monkeypatch.setenv("ARI_OS_BRAIN_DB", str(home / "brain.db"))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("vision backend should not be called when lens is off")

    monkeypatch.setattr("ari_os.tools.cortex.media.vision_bridge.see", fail_if_called)

    result = CliRunner().invoke(main, ["see", str(image)])

    assert result.exit_code == 0, result.output
    assert "brain.see is off" in result.output


def test_cortex_ears_default_off_exits_zero_without_backend_call(
    tmp_path: Path, monkeypatch
) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"fake audio")
    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("audio backend should not be called when ears is off")

    monkeypatch.setattr(
        "ari_os.tools.cortex.media.media_engines.transcribe_audio", fail_if_called
    )

    result = CliRunner().invoke(main, ["ears", str(audio)])

    assert result.exit_code == 0, result.output
    assert "cortex.ears is off" in result.output
