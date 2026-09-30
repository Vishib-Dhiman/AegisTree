"""Speech to text on this machine with Whisper (faster-whisper).

The browser records the user's voice and uploads the clip; it is transcribed
here, so audio never leaves the machine (unlike the browser's built-in speech
recognition, which Chrome sends to Google). The model is read only from the
local cache: download it once with scripts/get_speech_model.sh.
"""

from __future__ import annotations
import io
import threading
import time
from typing import Any, Dict, Optional

MAX_AUDIO_BYTES = 15 * 1024 * 1024  # about 15 minutes of Opus; far more than a prompt needs
MAX_AUDIO_SECONDS = 300
MODEL_REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
}


class SpeechError(Exception):
    """A user-facing reason transcription failed."""


def decode_audio(audio: bytes, sampling_rate: int = 16000):
    """Any browser recording (WebM/Opus, MP4/AAC, WAV, ...) as 16 kHz mono float32 samples.

    Done here rather than by faster-whisper, whose decoder passes arguments that
    newer PyAV releases no longer accept.
    """
    import av
    import numpy as np

    chunks = []
    with av.open(io.BytesIO(audio), mode="r") as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=sampling_rate)
        for frame in container.decode(audio=0):
            for resampled in resampler.resample(frame):
                chunks.append(resampled.to_ndarray())
        for resampled in resampler.resample(None):
            chunks.append(resampled.to_ndarray())
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return (np.concatenate(chunks, axis=1).reshape(-1).astype(np.float32) / 32768.0)


class SpeechToText:
    def __init__(self, model_size: str = "base", cpu_threads: int = 4):
        self.model_size = model_size
        self.cpu_threads = cpu_threads
        self._model = None
        self._lock = threading.Lock()

    @property
    def repo(self) -> str:
        return MODEL_REPOS.get(self.model_size, self.model_size)

    def status(self) -> Dict[str, Any]:
        """Whether transcription can work, and why not if it can't (no model load)."""
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return {"available": False, "reason": "faster-whisper is not installed (pip install faster-whisper)."}
        from huggingface_hub import try_to_load_from_cache

        cached = try_to_load_from_cache(self.repo, "model.bin")
        if not isinstance(cached, str):
            return {"available": False, "reason": "The speech model isn't downloaded yet: run scripts/get_speech_model.sh"}
        return {"available": True, "model": self.model_size}

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            try:
                self._model = WhisperModel(
                    self.repo, device="cpu", compute_type="int8",
                    cpu_threads=self.cpu_threads, local_files_only=True,
                )
            except Exception as ex:
                raise SpeechError(
                    f"The speech model couldn't be loaded ({type(ex).__name__}). "
                    "Download it with scripts/get_speech_model.sh"
                )
        return self._model

    def transcribe(self, audio: bytes, language: Optional[str] = None) -> Dict[str, Any]:
        if not audio:
            raise SpeechError("No audio was recorded.")
        if len(audio) > MAX_AUDIO_BYTES:
            raise SpeechError("That recording is too long. Keep voice prompts under a few minutes.")
        t0 = time.perf_counter()
        with self._lock:  # one transcription at a time keeps CPU free for the models
            model = self._load()
            try:
                samples = decode_audio(audio)
                if samples.size == 0:
                    raise SpeechError("No audio was recorded.")
                if samples.size / 16000 > MAX_AUDIO_SECONDS:
                    raise SpeechError("That recording is too long. Keep voice prompts under a few minutes.")
                segments, info = model.transcribe(
                    samples,
                    language=language or None,
                    beam_size=1,
                    vad_filter=True,
                    condition_on_previous_text=False,
                )
                text = " ".join(seg.text.strip() for seg in segments).strip()
            except SpeechError:
                raise
            except Exception as ex:
                raise SpeechError(f"Couldn't read that audio ({type(ex).__name__}). Try recording again.")
        return {
            "text": text,
            "language": info.language,
            "duration_s": round(info.duration, 2),
            "latency_ms": round((time.perf_counter() - t0) * 1000),
        }
