---
name: youtube-playlist-reader
description: "List all videos in a YouTube playlist with id, title, duration. No cookies needed for public playlists."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [youtube, playlist, yt-dlp, video, indexing]
    category: media
    related_skills: [video-preprocessor, video-to-knowledge-base]
---

# YouTube Playlist Reader

List all videos in a YouTube playlist. Returns structured metadata. No authentication needed for public playlists.

## When to use
Load this skill when you need to enumerate videos in a YouTube playlist before processing or indexing them.

## Usage

```python
from hermes_tools import terminal

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLxxx"

result = terminal(
    f'uvx yt-dlp --flat-playlist --print "%(id)s\t%(duration)s\t%(title)s" "{PLAYLIST_URL}" 2>/dev/null'
)

videos = []
for line in result['output'].strip().split('\n'):
    parts = line.split('\t')
    if len(parts) >= 3:
        videos.append({
            'id': parts[0],
            'url': f"https://youtube.com/watch?v={parts[0]}",
            'duration_seconds': int(parts[1] or 0),
            'duration_minutes': int(parts[1] or 0) // 60,
            'title': parts[2],
        })

print(f"Found {len(videos)} videos")
for v in videos:
    print(f"  {v['id']} | {v['duration_minutes']}min | {v['title'][:70]}")
```

## Filtering

```python
# Skip very short videos (< 5 min) and very long (> 3 hours)
videos = [v for v in videos if 300 <= v['duration_seconds'] <= 10800]

# Skip already indexed (compare against Chroma IDs)
# existing_ids = set(...)
# videos = [v for v in videos if f"video_{v['id']}" not in existing_ids]
```

## Enumerating all videos from a YouTube channel (two-step)

Running `yt-dlp --flat-playlist --print "%(id)s\t%(title)s" CHANNEL/playlists` gives **playlist IDs**, NOT video IDs. A single-step run on the channel will return ~N playlists (one ID per playlist), not the videos inside them.

**Correct two-step approach:**

```python
import subprocess

CHESS_KEYWORDS = ['keyword1', 'keyword2']  # topics to exclude
YTDLP = '/usr/local/bin/yt-dlp'  # use this path in container (not uvx yt-dlp)

# Step 1: enumerate playlist IDs + titles
r = subprocess.run([YTDLP, '--flat-playlist', '--print', '%(id)s\t%(title)s',
    'https://www.youtube.com/@CHANNEL/playlists'],
    capture_output=True, text=True, timeout=120)

playlists = []
for line in r.stdout.strip().splitlines():
    parts = line.split('\t', 1)
    if len(parts) == 2:
        pl_id, title = parts
        if not any(k in title for k in CHESS_KEYWORDS):
            playlists.append((pl_id, title))

# Step 2: enumerate video IDs per playlist, deduplicate
all_ids = set()
for pl_id, title in playlists:
    r2 = subprocess.run([YTDLP, '--flat-playlist', '--print', 'id',
        f'https://www.youtube.com/playlist?list={pl_id}'],
        capture_output=True, text=True, timeout=60)
    vids = [v.strip() for v in r2.stdout.strip().splitlines() if v.strip()]
    all_ids.update(vids)
```

Cross-playlist duplicates are common (348 raw → 141 unique for CMF channel). Always deduplicate with a set.

## Pitfalls
- **Channel URL gives playlist IDs, not video IDs.** See two-step section above.
- **`yt-dlp-fresh` is host-only.** Container workers must use `/usr/local/bin/yt-dlp`. No `--cookies-from-browser` in container.
- **For transcripts, prefer `mcp_mcp_youtube_transcript_get_transcript` MCP tool** over audio download + Whisper. Faster, no cookies, no binary needed. Use Whisper only when transcripts unavailable.
- Playlist listing works WITHOUT cookies even for age-restricted playlists (metadata only)
- Download (audio/video) requires cookies — that's handled by `video-preprocessor`
- Duration may be 0 for live streams or unprocessed uploads — filter these out
- Private playlists return 0 results without error — check `len(videos) == 0`
