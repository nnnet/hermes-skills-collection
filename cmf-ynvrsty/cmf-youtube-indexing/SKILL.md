---
name: cmf-youtube-indexing
description: "CMF-YNVRSTY pipeline orchestrator: load youtube-playlist-reader + video-preprocessor + video-to-knowledge-base. Contains CMF-specific domain mappings only."
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [CMF, YouTube, orchestrator, pipeline]
    related_skills: [youtube-playlist-reader, video-preprocessor, video-to-knowledge-base]
---

# CMF YouTube Indexing — Pipeline Orchestrator

This skill contains **only CMF-specific configuration**. All actual pipeline logic lives in the three universal skills below.

## Skills to load (in order)
1. `youtube-playlist-reader` — list videos from playlist
2. `video-preprocessor` — download + transcribe + frame analysis → structured document
3. `video-to-knowledge-base` — store in Chroma + wiki

## CMF Playlist → Domain mapping

| Playlist | Chroma collection | Wiki domain dir | Language |
|---|---|---|---|
| Quantitative Finance Weeks 1-5 | `cmf-quantitative-finance` | `finance` | `ru` |
| Advanced Quantitative Finance Weeks 1-2 | `cmf-quantitative-finance` | `finance` | `ru` |
| Лекции по финансовой математике | `cmf-quantitative-finance` | `finance` | `ru` |
| Options Trading | `cmf-quantitative-finance` | `finance` | `ru` |
| Algorithmic Trading / HFT | `cmf-quantitative-finance` | `finance` | `ru/en` |
| Алгоритмический трейдинг | `cmf-quantitative-finance` | `finance` | `ru` |
| Topics in Data Science | `cmf-machine-learning` | `ml` | `en` |
| Python | `cmf-machine-learning` | `ml` | `ru` |
| R | `cmf-machine-learning` | `ml` | `ru` |
| YNVRSTY: CMF Takes Charge #1-#Y | `cmf-quantitative-finance` | `finance` | `ru` |
| Подкасты ЦМФ | `cmf-banking` | `finance` | `ru` |
| Студенческие проекты YNVRSTY | `cmf-banking` | `finance` | `ru` |
| Криптовалюты | `cmf-banking` | `finance` | `ru` |
| Stochastic Processes | `cmf-mathematics` | `finance` | `ru` |
| Самые просматриваемые лекции | `cmf-quantitative-finance` | `finance` | `ru` |

## Wiki path
```
WIKI_PATH = "/opt/data/workspace/wiki"
```

## Full Playlist URLs (CMF-YNVRSTY channel — discovered 2026-05-15)
```python
CMF_PLAYLISTS = {
    # Quantitative Finance
    "qf_week1":       "https://www.youtube.com/playlist?list=PLBMgVdAlqlwyK3_ZKxq6GBCG0uljtBYy8",
    "qf_week2":       "https://www.youtube.com/playlist?list=PLBMgVdAlqlwwi8rLRFXz3arFC5HOF7bQF",
    "qf_week3":       "https://www.youtube.com/playlist?list=PLBMgVdAlqlwz4R5xAxSCKVhhN2NMDqAWR",
    "qf_week4":       "https://www.youtube.com/playlist?list=PLBMgVdAlqlwz5AeuZDpXWtQZpgw8q7ZyJ",
    "qf_week5":       "https://www.youtube.com/playlist?list=PLBMgVdAlqlwxPcWKvsQRq1M7X_kDt2wqv",
    "aqf_week1":      "https://www.youtube.com/playlist?list=PLBMgVdAlqlwxyLSEmahi6x8it-T5USqK_",
    "aqf_week2":      "https://www.youtube.com/playlist?list=PLBMgVdAlqlwy5t9afENsX9X5YwLuG_yBs",
    "fin_math":       "https://www.youtube.com/playlist?list=PLBMgVdAlqlwwt3F9fCxJ8xX2xeDVeXQxT",
    "options":        "https://www.youtube.com/playlist?list=PLBMgVdAlqlwzG2BUokUXeP55vFHMguJGK",
    "algo_en":        "https://www.youtube.com/playlist?list=PLBMgVdAlqlwx1RqawdYKSmiJCidOUMfVa",
    "algo_ru":        "https://www.youtube.com/playlist?list=PLBMgVdAlqlwwPOfPO0cSqHf-BsEdygklA",
    "hft":            "https://www.youtube.com/playlist?list=PLBMgVdAlqlwwIjwY7X3j4KfgY24VK1fCD",
    "stochastic":     "https://www.youtube.com/playlist?list=PLBMgVdAlqlww-x8OcNz8oGTjcjW3O7Te_",
    "top_viewed":     "https://www.youtube.com/playlist?list=PLBMgVdAlqlwxptlNPYLjHdRQaFJ10vXVw",
    # Data Science / ML
    "data_science":   "https://www.youtube.com/playlist?list=PLBMgVdAlqlwxraYIYO1jrcPYNcfnjfzYp",
    "python":         "https://www.youtube.com/playlist?list=PLBMgVdAlqlwwBdgsq3LZD-5x1fgTlLOnh",
    "r_lang":         "https://www.youtube.com/playlist?list=PLBMgVdAlqlwwhKVKdgvnx0jMYMGoRBfwV",
    # CMF Takes Charge (multi-domain)
    "takes_charge_1": "https://www.youtube.com/playlist?list=PLBMgVdAlqlwwy70OH2KMxUvco3PfNn9nZ1",
    "takes_charge_2": "https://www.youtube.com/playlist?list=PLBMgVdAlqlwzv6QCLDUW9jkrarQgEQ2_o",
    "takes_charge_3": "https://www.youtube.com/playlist?list=PLBMgVdAlqlwzceEKuAAmx8kseR9DROWj1",
    "takes_charge_4": "https://www.youtube.com/playlist?list=PLBMgVdAlqlwyCvxDmlsTiTypxJOvB7vwi",
    "takes_charge_5": "https://www.youtube.com/playlist?list=PLBMgVdAlqlwxv20h3vyvcTWXUOOnK6cID",
    "takes_charge_6": "https://www.youtube.com/playlist?list=PLBMgVdAlqlwxKbhZ64PBoF-gn8miI3uBq",
    "takes_charge_y": "https://www.youtube.com/playlist?list=PLBMgVdAlqlwwhGDhhJwsK8WbmTOLRFwyS",
    # Banking / Podcasts
    "podcasts":       "https://www.youtube.com/playlist?list=PLBMgVdAlqlwxHpk89KiEbvUFe2W9N-ac9",
    "student_proj":   "https://www.youtube.com/playlist?list=PLBMgVdAlqlwy-nkM6ZBCUuoWS_vk_NR1p",
    "crypto":         "https://www.youtube.com/playlist?list=PLBMgVdAlqlwxcblBqwTqGu3IA-_VEzzBy",
}
```

## Cookies
```
COOKIES_BROWSER = "firefox:/opt/firefox-profile"
```
yt-dlp reads cookies directly from the Firefox profile mounted read-only at `/opt/firefox-profile` (must contain `cookies.sqlite`). If the profile mount is missing → `kanban_block` immediately. Never fabricate results.

## Verification gate (mandatory before kanban_complete)
- `count_after > count_before` in Chroma
- Wiki page file exists on disk
- Raw transcript saved in `wiki/raw/transcripts/`

## Pitfalls

- **CRITICAL — Use yt-dlp+Whisper, NOT the YouTube Captions API, for CMF transcription.** The MCP transcript tool (caption-based) only covers videos where YouTube auto-captions exist. For CMF: 69 videos identified, only 15 had captions → 22% coverage, then YouTube anti-bot blocked further requests. The correct pipeline for CMF is yt-dlp audio download + Whisper `medium` model (minimum for Russian math speech; `base` fails). At ~37 sec/min CPU this is slow but produces real transcripts for all videos regardless of caption availability. Never use the captions API as the primary method for a CMF ingest task.

- **ValidationError from MCP transcript tool = URL format problem, NOT server down.** The tool requires exactly `https://www.youtube.com/watch?v=VIDEO_ID`. Any deviation (shorts URL, playlist params appended, etc.) causes ValidationError. On ValidationError: skip that video and continue — do NOT retry 4× or block the task.
- **"No captions found" ≠ server failure.** Try `lang="ru"` then `lang="en"` before skipping. A video with no captions should be skipped silently; the task should continue to the next video.
- **Student Projects and Podcasts playlists have NO YouTube captions at all.** Confirmed 2026-05-15: PLBMgVdAlqlwypXtAJZ4bjnny72KPcFstc (Student Projects) and PLBMgVdAlqlwxHpk89KiEbvUFe2W9N-ac9 (Podcasts) — all tested videos returned "No captions found". These playlists **cannot be transcript-indexed** via MCP tool without channel owner enabling auto-captions in YouTube Studio first.
- **Use `--cookies-from-browser firefox:/opt/firefox-profile` for yt-dlp**, NOT a `.txt` cookie file. The Firefox profile is mounted at `/opt/firefox-profile` with `cookies.sqlite` present. If `yt-dlp-fresh` not in PATH, use `uvx yt-dlp` as a drop-in with identical flags.
- **Playlist video ID extraction via yt-dlp**: Use `yt-dlp-fresh --flat-playlist` (the bundled auto-update wrapper, see video-preprocessor skill) for metadata listing — this works without cookies. Regular `yt-dlp` download is blocked.
- All pipeline pitfalls are documented in `video-preprocessor` and `video-to-knowledge-base`
- This skill only adds CMF-specific config — do not duplicate pipeline logic here
