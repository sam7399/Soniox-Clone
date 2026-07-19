# Personify Voice AI

*Every voice. Every language. Crafted for you.* — by Personify Crafters

A Windows desktop application for multilingual speech-to-text,
translation, AI meeting summaries and text-to-speech — with both fully
offline (local Whisper) and cloud provider modes.

**Version 1.0 — core pipeline release.** See *Roadmap* below for what
is and isn't included yet.

## What v1.0 does

- **Import audio/video** (MP3, WAV, M4A, FLAC, OGG, MP4, MOV, MKV,
  AVI, WEBM, …) by browse or drag-and-drop; automatic audio
  extraction, duplicate detection by file hash, long-file chunking.
- **Record from the microphone** with a visible recording indicator,
  pause/resume, level meter, and near-live preview transcription
  (local engine). The full recording gets a full-quality pass when you
  stop.
- **Transcribe** offline (faster-whisper, ~100 languages, CPU or
  NVIDIA GPU) or via cloud adapters: OpenAI Whisper, Deepgram
  (diarization), Soniox (diarization + per-word language, great for
  Hinglish/mixed-language). Configurable fallback provider.
- **Mixed-language support**: per-segment language labels; the
  original transcript is never overwritten.
- **Edit transcripts**: editable segments, low-confidence
  highlighting, speaker renaming, revert-to-AI-original per row,
  synchronized audio playback with click-to-jump and speed control.
- **Translate** transcripts (segment-aligned, glossary +
  do-not-translate terms) — original kept separately.
- **AI summaries**: structured meeting reports (summary, decisions,
  action items, risks, open questions, sentiment) with selectable
  templates; always labelled AI-generated and editable.
- **Text-to-speech**: offline Windows voices or OpenAI TTS, speed
  control, WAV/MP3, generation history.
- **Custom vocabulary**: wrong-spelling correction, categories, CSV
  import/export, do-not-translate protection.
- **Exports**: DOCX, PDF (watermark + page numbers), XLSX (formatted,
  frozen header, filters), TXT, SRT, VTT, JSON, HTML, Markdown.
- **Privacy Mode**: one switch enforces local-only processing — cloud
  providers are blocked at the registry level.
- **Cost control**: per-operation cost estimates, month-to-date
  spend, monthly budget with warning threshold.
- **Crash-safe jobs**: the queue is persisted in SQLite; interrupted
  jobs resume from the last completed chunk after restart.
- **Security**: API keys in Windows Credential Manager (or an
  encrypted local file), never in plain text or logs.

## Quick start (development)

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m app.main
```

FFmpeg must be on PATH for development (`winget install ffmpeg`), or
run `build\get_ffmpeg.ps1`.

## Building the Windows .exe + installer

1. On a 64-bit Windows 10/11 machine with Python 3.12+:
   `build\build_windows.bat`
   (creates venv → installs deps → downloads FFmpeg → runs tests →
   builds `dist\GlobalVoiceAI\GlobalVoiceAI.exe`)
2. Install [Inno Setup 6](https://jrsoftware.org/isinfo.php) and run
   `iscc build\installer.iss` → produces
   `GlobalVoiceAI-Setup-1.0.0.exe`.
3. Portable version: copy `dist\GlobalVoiceAI` anywhere and create an
   empty `portable.flag` file next to the exe (data then lives in
   `.\data`).

Updates never touch user data: everything lives in
`%APPDATA%\GlobalVoiceAI` (database, config, models, logs, backups).

## Configuration

Open **Settings** in the app:

- Choose default + fallback transcription provider and local model
  size (tiny → large-v3; larger = more accurate, slower).
- Paste API keys for OpenAI / Deepgram / Soniox — stored encrypted.
- Privacy Mode, noise reduction, diarization, monthly budget.

No API keys are required for offline use; the local model downloads
automatically on first transcription (needs internet once, or copy a
model folder into `%APPDATA%\GlobalVoiceAI\models`).

## Testing

```bat
python -m pytest tests -q
```

23 tests cover the database, job recovery, vocabulary correction,
credential encryption, all nine export formats, privacy-mode
enforcement, provider fallback, Soniox token grouping, duplicate
detection and the full pipeline with a mocked STT provider.

## Legal & ethics notes

- Always obtain consent before recording; laws vary by jurisdiction
  and you are responsible for compliance. The app always shows a
  visible indicator while recording — there is no hidden recording
  mode, by design.
- Cloud modes send audio/transcripts to the configured provider; the
  active provider is always visible in the status bar.
- Transcripts, translations and summaries are AI-generated and may be
  wrong; TTS output is synthetic and labelled as such.

## Roadmap (not yet in v1.0)

Multi-user roles & login, dashboard filters, folder-watch automation,
scheduled/encrypted backups, local REST API, Zoom/Teams/Drive
integrations, offline translation models, first-run wizard, update
checker, light theme. The database schema and provider registry were
designed with these in mind.

## Project layout

```
app/
  config.py          central config (JSON in %APPDATA%)
  logging_setup.py   rotating file logs
  main.py            entry point
  db/                SQLAlchemy models + engine + crash recovery
  security/          encrypted credential store
  core/              audio (FFmpeg), pipeline, jobs, vocab, costs,
                     services (translate/summarize), exporters
  providers/         base interfaces, registry, stt/ translate/ tts/ llm/
  workers/           microphone recorder
  ui/                PySide6 main window + pages
build/               PyInstaller spec, Inno Setup script, build.bat
tests/               pytest suite
```
