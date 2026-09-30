import io
import shutil
import subprocess
from pathlib import Path

import pytest

from clearsky.speech import MAX_AUDIO_BYTES, SpeechError, SpeechToText, decode_audio

PHRASE = "Add a rotate session token function using our current vault standard."


def _webm_opus(aiff: Path) -> bytes:
    """Re-encode like Chrome's MediaRecorder does (WebM container, Opus codec)."""
    import av

    out = io.BytesIO()
    with av.open(str(aiff)) as src, av.open(out, mode="w", format="webm") as dst:
        stream = dst.add_stream("libopus", rate=48000)
        stream.layout = "mono"
        resampler = av.AudioResampler(format=stream.format.name, layout="mono", rate=48000)
        for frame in src.decode(audio=0):
            for f in resampler.resample(frame):
                for packet in stream.encode(f):
                    dst.mux(packet)
        for packet in stream.encode(None):
            dst.mux(packet)
    return out.getvalue()


@pytest.fixture(scope="module")
def spoken(tmp_path_factory) -> bytes:
    if not shutil.which("say"):
        pytest.skip("needs macOS `say` to synthesise speech")
    aiff = tmp_path_factory.mktemp("voice") / "prompt.aiff"
    subprocess.run(["say", "-o", str(aiff), PHRASE], check=True)
    return _webm_opus(aiff)


@pytest.fixture(scope="module")
def stt() -> SpeechToText:
    s = SpeechToText()
    if not s.status()["available"]:
        pytest.skip("speech model not downloaded (scripts/get_speech_model.sh)")
    return s


def test_browser_recording_is_transcribed_locally(stt, spoken):
    result = stt.transcribe(spoken)
    words = result["text"].lower()
    for word in ("rotate", "session", "token", "vault"):
        assert word in words, result
    assert result["language"] == "en" and result["duration_s"] > 1


def test_decode_gives_16khz_mono_samples(spoken):
    samples = decode_audio(spoken)
    assert samples.ndim == 1 and 2 * 16000 < samples.size < 10 * 16000
    assert float(abs(samples).max()) <= 1.0


@pytest.mark.parametrize("audio, message", [
    (b"", "No audio"),
    (b"definitely not audio" * 20, "Couldn't read that audio"),
])
def test_bad_audio_is_explained(stt, audio, message):
    with pytest.raises(SpeechError) as ex:
        stt.transcribe(audio)
    assert message in str(ex.value)


def test_oversized_audio_is_refused_before_decoding():
    with pytest.raises(SpeechError) as ex:
        SpeechToText().transcribe(b"x" * (MAX_AUDIO_BYTES + 1))
    assert "too long" in str(ex.value)


def test_missing_model_is_reported_not_crashed():
    status = SpeechToText(model_size="Systran/not-a-real-whisper-model").status()
    assert status["available"] is False and "get_speech_model.sh" in status["reason"]
