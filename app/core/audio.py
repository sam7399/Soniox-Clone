"""FFmpeg-based audio handling: probing, extraction, normalization,
chunking and hashing. FFmpeg is bundled by the installer into
<app>/ffmpeg/ffmpeg.exe; falls back to system PATH for development."""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma",
              ".opus", ".amr"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv", ".m4v",
              ".mpg", ".mpeg", ".3gp"}
SUPPORTED_EXTS = AUDIO_EXTS | VIDEO_EXTS


class AudioError(Exception):
    def __init__(self, message: str, user_message: str) -> None:
        super().__init__(message)
        self.user_message = user_message


def find_ffmpeg(tool: str = "ffmpeg") -> str:
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).parent / "ffmpeg" / f"{tool}.exe"
        if bundled.exists():
            return str(bundled)
    found = shutil.which(tool)
    if found:
        return found
    raise AudioError(f"{tool} not found",
                     "The audio engine (FFmpeg) is missing. Please "
                     "reinstall the application.")


def _run(cmd: list[str], timeout_s: int = 3600) -> subprocess.CompletedProcess:
    log.debug("run: %s", " ".join(cmd))
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as e:
        raise AudioError("ffmpeg timeout",
                         "Audio processing took too long and was "
                         "stopped.") from e


def file_hash(path: Path, algo: str = "sha256") -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def probe(path: Path) -> dict:
    """Return {'duration_s': float, 'has_audio': bool, 'codec': str}."""
    if not path.exists():
        raise AudioError("missing file", "The selected file no longer "
                         "exists.")
    cp = _run([find_ffmpeg("ffprobe"), "-v", "quiet", "-print_format",
               "json", "-show_format", "-show_streams", str(path)],
              timeout_s=60)
    if cp.returncode != 0:
        raise AudioError(f"ffprobe failed: {cp.stderr[:300]}",
                         "This file could not be read. It may be "
                         "corrupted or in an unsupported format.")
    try:
        data = json.loads(cp.stdout)
    except json.JSONDecodeError as e:
        raise AudioError("ffprobe bad json", "This file could not be "
                         "analyzed.") from e
    streams = data.get("streams", [])
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    duration = float(data.get("format", {}).get("duration", 0) or 0)
    return {"duration_s": duration,
            "has_audio": bool(audio_streams),
            "codec": audio_streams[0].get("codec_name", "")
            if audio_streams else ""}


def to_wav_16k_mono(src: Path, dst: Path, noise_reduction: bool = False,
                    normalize: bool = False) -> Path:
    """Extract/convert any supported file to 16 kHz mono WAV for STT."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    filters = []
    if noise_reduction:
        filters.append("afftdn=nf=-25")        # conservative denoise
    if normalize:
        filters.append("loudnorm=I=-19:TP=-2")  # gentle loudness norm
    cmd = [find_ffmpeg(), "-y", "-i", str(src), "-vn",
           "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"]
    if filters:
        cmd += ["-af", ",".join(filters)]
    cmd.append(str(dst))
    cp = _run(cmd)
    if cp.returncode != 0 or not dst.exists():
        raise AudioError(f"ffmpeg convert failed: {cp.stderr[:300]}",
                         "The audio could not be converted. The file may "
                         "be corrupted or contain no audio track.")
    return dst


def split_chunks(wav: Path, out_dir: Path, chunk_s: int = 300,
                 overlap_s: int = 2) -> list[tuple[Path, float]]:
    """Split a long WAV into chunks. Returns [(path, start_offset_s)].
    Short files are returned as a single chunk without re-encoding."""
    info = probe(wav)
    duration = info["duration_s"]
    if duration <= chunk_s + overlap_s:
        return [(wav, 0.0)]
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[tuple[Path, float]] = []
    start = 0.0
    i = 0
    while start < duration:
        length = min(chunk_s + overlap_s, duration - start)
        part = out_dir / f"{wav.stem}_chunk{i:03d}.wav"
        cp = _run([find_ffmpeg(), "-y", "-ss", str(start), "-t",
                   str(length), "-i", str(wav), "-c", "copy", str(part)])
        if cp.returncode != 0 or not part.exists():
            raise AudioError(f"chunking failed: {cp.stderr[:300]}",
                             "The recording could not be split for "
                             "processing.")
        chunks.append((part, start))
        start += chunk_s
        i += 1
    return chunks


def has_speech_energy(wav: Path, silence_db: float = -45.0) -> bool:
    """Cheap silence detector: mean volume above threshold."""
    cp = _run([find_ffmpeg(), "-i", str(wav), "-af", "volumedetect",
               "-f", "null", "-"], timeout_s=600)
    for line in (cp.stderr or "").splitlines():
        if "mean_volume:" in line:
            try:
                mean = float(line.split("mean_volume:")[1]
                             .replace("dB", "").strip())
                return mean > silence_db
            except ValueError:
                return True
    return True
