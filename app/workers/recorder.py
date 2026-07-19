"""Microphone recorder with live level metering and near-live
transcription support.

Records 16 kHz mono PCM to a WAV file in the app work folder. A visible
recording state is exposed so the UI can always show an indicator while
recording is active (no hidden recording, by design). Optionally emits
periodic audio windows so the UI can run rolling local transcription.
"""
from __future__ import annotations

import logging
import threading
import time
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from app.config import app_data_dir, get_config_manager

log = logging.getLogger(__name__)


class RecorderError(Exception):
    def __init__(self, message: str, user_message: str) -> None:
        super().__init__(message)
        self.user_message = user_message


def list_input_devices() -> list[tuple[int, str]]:
    try:
        import sounddevice as sd
        devices = sd.query_devices()
    except Exception as e:
        raise RecorderError(f"sounddevice failed: {e}",
                            "No microphone system detected. Check your "
                            "audio drivers.") from e
    return [(i, d["name"]) for i, d in enumerate(devices)
            if d.get("max_input_channels", 0) > 0]


class Recorder:
    """Threaded WAV recorder. Callbacks are invoked from the audio
    thread; UI code must marshal to the main thread itself."""

    def __init__(self,
                 on_level: Callable[[float], None] | None = None,
                 on_window: Callable[[Path], None] | None = None,
                 on_chunk: Callable[[bytes], None] | None = None,
                 window_s: float = 6.0) -> None:
        self.on_level = on_level
        self.on_window = on_window
        self.on_chunk = on_chunk    # raw 16-bit PCM, for streaming STT
        self.window_s = window_s
        self.sample_rate = 16000
        self._frames: list[np.ndarray] = []
        self._window_frames: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()
        self._recording = False
        self._paused = False
        self._started_at = 0.0
        self.out_path: Path | None = None

    # -- state --------------------------------------------------------
    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self._started_at if self._recording \
            else 0.0

    # -- control ------------------------------------------------------
    def start(self, device_index: int | None = None) -> None:
        if self._recording:
            return
        try:
            import sounddevice as sd
        except Exception as e:
            raise RecorderError(str(e),
                                "Audio recording is unavailable on this "
                                "computer (no audio backend).") from e
        cfg = get_config_manager().config
        self.sample_rate = cfg.sample_rate or 16000

        def callback(indata, frames, t, status) -> None:  # noqa: ANN001
            if status:
                log.debug("audio status: %s", status)
            if self._paused:
                return
            mono = indata[:, 0].copy()
            with self._lock:
                self._frames.append(mono)
                self._window_frames.append(mono)
            if self.on_level is not None:
                self.on_level(float(np.abs(mono).mean()) * 3.0)
            if self.on_chunk is not None:
                pcm16 = (np.clip(mono, -1, 1) * 32767).astype(np.int16)
                self.on_chunk(pcm16.tobytes())
            if self.on_window is not None:
                win_len = sum(len(f) for f in self._window_frames)
                if win_len >= self.window_s * self.sample_rate:
                    self._flush_window()

        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate, channels=1, dtype="float32",
                device=device_index, callback=callback)
            self._stream.start()
        except Exception as e:
            raise RecorderError(str(e),
                                "The microphone could not be opened. It "
                                "may be in use by another application, or "
                                "microphone permission is denied in "
                                "Windows Settings > Privacy.") from e
        self._frames = []
        self._window_frames = []
        self._recording = True
        self._paused = False
        self._started_at = time.monotonic()
        work = app_data_dir() / "recordings"
        work.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.out_path = work / f"recording_{stamp}.wav"
        log.info("Recording started -> %s", self.out_path)

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def stop(self) -> Path | None:
        if not self._recording:
            return None
        self._recording = False
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        finally:
            self._stream = None
        with self._lock:
            frames = self._frames
            self._frames = []
            self._window_frames = []
        if not frames or self.out_path is None:
            return None
        data = np.concatenate(frames)
        pcm = (np.clip(data, -1, 1) * 32767).astype(np.int16)
        with wave.open(str(self.out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sample_rate)
            w.writeframes(pcm.tobytes())
        log.info("Recording saved: %s (%.1fs)", self.out_path,
                 len(data) / self.sample_rate)
        return self.out_path

    # -- helpers ------------------------------------------------------
    def _flush_window(self) -> None:
        with self._lock:
            frames = self._window_frames
            self._window_frames = []
        if not frames or self.on_window is None:
            return
        data = np.concatenate(frames)
        pcm = (np.clip(data, -1, 1) * 32767).astype(np.int16)
        work = app_data_dir() / "work"
        work.mkdir(exist_ok=True)
        path = work / f"live_window_{time.monotonic_ns()}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sample_rate)
            w.writeframes(pcm.tobytes())
        try:
            self.on_window(path)
        except Exception:
            log.exception("live window callback failed")
