---
name: video-preprocessor
description: "Universal video → structured document: download (yt-dlp), audio extraction, faster-whisper transcription, ffmpeg frame extraction, vision frame analysis. Works with any URL yt-dlp supports or local file."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [video, transcription, whisper, ffmpeg, yt-dlp, vision, preprocessing]
    category: media
    related_skills: [youtube-playlist-reader, video-to-knowledge-base]
---

# Video Preprocessor

Convert any video (YouTube URL, Vimeo, local file) into a structured document ready for indexing.

**Output:** `{id, title, url, duration_seconds, language, transcript, visual_notes, metadata}`

## When to use
Load this skill before indexing video content into Chroma or a wiki. Works with any source yt-dlp supports.

**Fast path first:** Before running the full yt-dlp+whisper pipeline, try `youtube-content` skill's `fetch_transcript.py` — if YouTube captions exist, it returns a transcript in seconds. Only fall back to this skill if captions are unavailable ("No captions found").

## Subtitle-Only Extraction (fast path for auto-caption channels)

When a YouTube channel has **auto-generated captions** (e.g. `ru (auto)` in `--list-subs`), this path is 10–100× faster than the full download→Whisper pipeline: no audio download, no GPU, ~1–3 sec per video.

**Try this BEFORE the full pipeline.** Fall back to Whisper only when `--list-subs` shows no auto captions.

```bash
# Single video
yt-dlp \
  --cookies-from-browser firefox:/opt/firefox-profile \
  -f 'sb0/sb1/sb2' \
  --write-auto-sub --sub-lang ru --skip-download \
  -o "/tmp/yt/%(id)s" \
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

**Why `-f 'sb0/sb1/sb2'`:** yt-dlp's format resolver sometimes fails against YouTube's n-challenge signature, returning "Requested format is not available" for normal video/audio formats. Storyboard formats (`sb0`, `sb1`, `sb2`) are served from a different CDN path and skip the n-challenge entirely. Subtitle download succeeds as a side effect. Adding `/sb1/sb2` as fallback handles videos that lack `sb0`.

> **Do NOT pass `--sub-format vtt`** — it conflicts with `--skip-download` on many yt-dlp versions and causes "Requested format not available" errors. Omit it; yt-dlp picks VTT automatically.

**Batch download (playlist or ID list):**
```bash
# One URL per line in urls.txt
yt-dlp \
  --cookies-from-browser firefox:/opt/firefox-profile \
  -f 'sb0/sb1/sb2' \
  --write-auto-sub --sub-lang ru --skip-download \
  --sleep-interval 1 --max-sleep-interval 3 \
  -o "/opt/data/workspace/<project>/raw/youtube/%(id)s" \
  -a /tmp/urls.txt
```

**On HTTP 429:** Do NOT retry immediately. Wait 30–60 min (YouTube's rate-limit window), then re-run with `--sleep-interval 3`. Save missing IDs to a retry file and cron it.

**VTT → plain text cleanup** (after batch download):
```bash
for vtt in /path/to/raw/youtube/*.ru.vtt; do
  txt="${vtt%.ru.vtt}.txt"
  grep -v '^WEBVTT' "$vtt" \
    | grep -v '^\s*$' \
    | grep -v '^[0-9]\{2\}:[0-9]\{2\}' \
    | sed 's/<[^>]*>//g' \
    | awk '!seen[$0]++' > "$txt"
done
```

**Limitations:** channels that disable captions entirely → fall back to Whisper pipeline (Steps 1–4 below).

---

## Prerequisites — CHECK BEFORE PROCESSING

```python
from hermes_tools import terminal
import os, sys

COOKIES_BROWSER = "firefox:/opt/firefox-profile"
FIREFOX_PROFILE = "/opt/firefox-profile"
WORK_DIR = "/tmp/video_preprocess"

# 1. Ensure faster-whisper is installed (not in Hermes venv by default)
try:
    import faster_whisper
except ImportError:
    # uv is at /usr/local/bin/uv; `pip` and `python` are NOT in bash PATH
    r = terminal(f"uv pip install faster-whisper --python {sys.executable} 2>&1 | tail -5")
    try:
        import faster_whisper
    except ImportError:
        raise RuntimeError(f"faster-whisper install failed: {r['output']}")
        # → kanban_block(reason=f"Cannot install faster-whisper: {r['output']}")

missing = []
if not os.path.isdir(FIREFOX_PROFILE) or not os.path.exists(f"{FIREFOX_PROFILE}/cookies.sqlite"):
    missing.append(f"Firefox profile not mounted at {FIREFOX_PROFILE} — check compose mount")
    missing.append("Fix: ensure docker-compose mounts the host Firefox profile read-only to /opt/firefox-profile (must contain cookies.sqlite)")
    missing.append("Note: yt-dlp reads cookies directly from the Firefox profile via --cookies-from-browser; no .txt export needed.")

if missing:
    print("BLOCK REQUIRED:\n" + "\n".join(missing))
    # → kanban_block(reason="\n".join(missing))
else:
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(f"{WORK_DIR}/frames", exist_ok=True)
    print("Prerequisites OK")
```

> **If Firefox profile not mounted → `kanban_block` immediately. Never fabricate output.**

## Step 1: Download audio

```python
from hermes_tools import terminal
import os

def download_audio(video_url, video_id, work_dir, cookies_browser):
    audio_path = f"{work_dir}/{video_id}.mp3"
    if os.path.exists(audio_path):
        print(f"Audio already exists: {audio_path}")
        return audio_path

    r = terminal(
        f'yt-dlp-fresh --cookies-from-browser {cookies_browser} -x --audio-format mp3 --audio-quality 5 '
        f'-o "{work_dir}/%(id)s.%(ext)s" "{video_url}" 2>&1 | tail -10'
    )
    if r['exit_code'] != 0 or 'ERROR' in r['output']:
        print("AUDIO DOWNLOAD FAILED:", r['output'][-500:])
        return None  # → kanban_block
    return audio_path
```

## Step 2: Download video for frames (optional but recommended)

```python
import glob

def download_video(video_url, video_id, work_dir, cookies_browser):
    r = terminal(
        f'yt-dlp-fresh --cookies-from-browser {cookies_browser} -f "worst[ext=mp4]/worst[ext=webm]/worst" '
        f'-o "{work_dir}/%(id)s_vid.%(ext)s" "{video_url}" 2>&1 | tail -5'
    )
    matches = glob.glob(f"{work_dir}/{video_id}_vid.*")
    return matches[0] if matches else None  # None = non-fatal, audio-only mode
```

## Step 3: Extract 1 frame per minute

```python
import glob

def extract_frames(video_path, video_id, work_dir):
    if not video_path:
        return []
    r = terminal(
        f'ffmpeg -i "{video_path}" -vf "fps=1/60" '
        f'"{work_dir}/frames/{video_id}_%04d.jpg" -y 2>&1 | tail -3'
    )
    return sorted(glob.glob(f"{work_dir}/frames/{video_id}_*.jpg"))
```

## Step 4: Transcribe with faster-whisper

```python
import json

def transcribe(audio_path, language="ru"):
    # NOTE: 'base' model is too weak for Russian academic/math speech — use 'medium' minimum
    # 'medium' benchmarked at ~37 sec/min of audio on CPU (int8), quality is good
    MODEL = "medium"

    r = terminal(f'''cd /opt/hermes && .venv/bin/python3 -c "
import sys, json
sys.path.insert(0, '/opt/hermes')
from tools.transcription_tools import transcribe_audio
result = transcribe_audio('{audio_path}', model='{MODEL}')
print(json.dumps({{'success': result.get('success', False), 'transcript': result.get('transcript', '')[:60000]}}))
" 2>&1''')
    try:
        data = json.loads(r['output'].strip().split('\n')[-1])
        return data.get('transcript', '')
    except Exception:
        pass

    # Fallback: uvx faster-whisper
    r = terminal(f'''uvx --with faster-whisper python3 -c "
from faster_whisper import WhisperModel
model = WhisperModel('{MODEL}', device='cpu', compute_type='int8')
segs, _ = model.transcribe('{audio_path}', language='{language}', beam_size=5)
print(' '.join(s.text for s in segs)[:60000])
"''')
    return r['output'].strip()
```

**Language codes:** `ru` (Russian), `en` (English), `auto` (detect automatically)

## Step 5: Analyze key frames with vision

```python
# Use vision_analyze tool — call directly, not via execute_code
# Analyze every 5th frame, max 20 frames

def analyze_frames(frames):
    key_frames = frames[::5][:20]
    notes = []
    for frame_path in key_frames:
        # result = vision_analyze(frame_path,
        #   "Describe academic/lecture content: formulas, diagrams, slide titles, key terms. Be concise (2-3 sentences).")
        # notes.append(result)
        pass
    return "\n".join(notes)
```

## Step 6: Assemble structured document

```python
def assemble_document(video_id, title, url, duration_seconds, language, transcript, visual_notes,
                      domain="", author="", participants=None, source_created_date="",
                      project_id="CMF-YNVRSTY", processor_agent="youtube-indexer"):
    from datetime import datetime, timezone
    import hashlib
    body = f"Title: {title}\nDuration: {duration_seconds // 60} min\nURL: {url}\nDomain: {domain}\n\n=== TRANSCRIPT ===\n{transcript}\n\n=== VISUAL CONTENT (slides/diagrams) ===\n{visual_notes if visual_notes else '(no frames analyzed)'}\n"
    return {
        "id": f"video_{video_id}",
        "title": title,
        "url": url,
        "duration_seconds": duration_seconds,
        "language": language,
        "domain": domain,
        "transcript": transcript,
        "visual_notes": visual_notes,
        "text": body,
        "metadata": {
            # Layer 1 — Provenance (mandatory per data-governance-metadata-schema)
            "source_url": url,
            "source_type": "youtube_video",
            "source_created_date": source_created_date,
            "author": author,
            "participants": participants or [],
            "processor_agent": processor_agent,
            "processed_date": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            # Layer 2 — Semantic
            "video_id": video_id,
            "title": title,
            "duration_seconds": duration_seconds,
            "domains": [domain] if domain else [],
            "language": language,
            # Layer 3 — Technical
            "content_hash": hashlib.sha256(body.encode()).hexdigest(),
            "has_visual_analysis": bool(visual_notes),
        }
    }
```

## Full pipeline (single video)

```python
COOKIES_BROWSER = "firefox:/opt/firefox-profile"
WORK_DIR = "/tmp/video_preprocess"
VIDEO_URL = "https://youtube.com/watch?v=VIDEO_ID"
VIDEO_ID = "VIDEO_ID"
LANGUAGE = "ru"
DOMAIN = "stochastic processes"

audio = download_audio(VIDEO_URL, VIDEO_ID, WORK_DIR, COOKIES_BROWSER)
if not audio:
    pass  # → kanban_block

video_file = download_video(VIDEO_URL, VIDEO_ID, WORK_DIR, COOKIES_BROWSER)
frames = extract_frames(video_file, VIDEO_ID, WORK_DIR)
transcript = transcribe(audio, language=LANGUAGE)

if not transcript:
    pass  # → kanban_block: transcription returned empty

visual_notes = analyze_frames(frames)  # use vision_analyze tool for each frame

doc = assemble_document(VIDEO_ID, title, VIDEO_URL, duration_seconds, LANGUAGE, transcript, visual_notes, DOMAIN)
print(f"Document ready: {len(doc['text'])} chars, transcript: {len(transcript)} chars")
```

## Installing yt-dlp (if not available)
In the Hermes gateway, prefer the bundled `yt-dlp-fresh` wrapper (auto-updates daily into
`/opt/data/.python-user`, no install needed). If working outside the gateway, fall back to
`uvx yt-dlp` (ephemeral venv) or curl binary install:
```bash
curl -sL https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /tmp/yt-dlp
chmod +x /tmp/yt-dlp
/tmp/yt-dlp --version
```
Note: `/usr/local/bin/` is often read-only in containers — use `/tmp/` instead.

## Whisper API (GPU-backed, preferred)

**GPU Whisper server:** always running, never spin up locally. Address depends on context:
- **execute_code / sandbox / host terminal** → `http://localhost:8504/v1`
- **Docker container** (hermes-agent) → `http://host.docker.internal:8504/v1`
OpenAI-compatible `/v1/audio/transcriptions` endpoint.

Available models:
- `deepdml/faster-whisper-large-v3-turbo-ct2` — default, high quality, GPU-accelerated
- `Systran/faster-whisper-small` — fallback, lighter

Use this instead of running Whisper locally (no CPU transcription needed). Example:
```bash
curl http://host.docker.internal:8504/v1/audio/transcriptions \
  -F file=@audio.mp3 \
  -F model=deepdml/faster-whisper-large-v3-turbo-ct2 \
  -F language=ru
```

Or via Python openai client:
```python
import openai
client = openai.OpenAI(base_url="http://host.docker.internal:8504/v1", api_key="not-needed")
with open("audio.mp3", "rb") as f:
    result = client.audio.transcriptions.create(model="deepdml/faster-whisper-large-v3-turbo-ct2", file=f, language="ru")
print(result.text)
```

**Do NOT spin up local Whisper** — the GPU server is already running and is much faster.

## Pitfalls
1. **Firefox profile not mounted at `/opt/firefox-profile` → BLOCK immediately**, never fake output
2. **Cookies are read directly from the Firefox profile** via `--cookies-from-browser firefox:/opt/firefox-profile`. The host Firefox profile is mounted read-only into the container at `/opt/firefox-profile`; no `.txt` export is used or needed.
3. **Mount must be read-only and contain `cookies.sqlite`** — if Firefox is running on the host with the same profile, yt-dlp can still read it (read-only mount avoids lock contention); permissions on the mount must allow the container user to read the SQLite files.
2. **`ERROR` in yt-dlp output** = download failed → BLOCK, don't continue to transcription
3. **Empty transcript** on non-silent video = transcription failed → BLOCK
4. **Local file input**: skip download steps, pass file path directly to `transcribe()` and `extract_frames()`
5. **Language detection**: pass `language='auto'` if unsure, but explicit code is faster and more accurate
6. **Long videos (>60 min)**: call `kanban_heartbeat()` after each major step
7. **frame extraction**: `fps=1/60` = 1 frame per minute. For dense slides, use `fps=1/30`
8. **`--sub-format vtt` + `--skip-download` conflict:** passing `--sub-format vtt` alongside `--skip-download` causes "Requested format is not available" on many yt-dlp versions. Omit `--sub-format` entirely — yt-dlp selects VTT automatically for subtitle-only downloads.
9. **n-challenge "Requested format is not available":** if yt-dlp fails format resolution with this error on a normal `-f bestaudio` call, switch to `-f 'sb0/sb1/sb2'` (storyboard format) which bypasses the n-challenge. Works for subtitle-only extraction; does NOT help for full audio downloads that require the actual stream.
10. **Cleanup**: `rm -rf {WORK_DIR}/{VIDEO_ID}*` after successful indexing to free disk
