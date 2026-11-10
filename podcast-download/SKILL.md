---
name: podcast-download
description: Download podcast episodes by title, Apple link, or RSS.
---

# Podcast Download

Find a specific podcast episode by title (often from a screenshot, e.g. "Episode 244: The China Syndrome"), an Apple Podcasts link, or an RSS feed — then download the audio, verify it, and save show notes.

Main path: `scripts/podcast_download.py` in this skill dir. It handles the China-network split — the iTunes API works direct, while anchor.fm / Spotify / CloudFront audio get a region-blocked 403 direct and need the Clash proxy at `http://127.0.0.1:7897`.

## When to Use

- User wants a podcast episode downloaded: gives a title/episode number (maybe a screenshot), an Apple Podcasts link, or an RSS URL.
- "找一下这期播客/帮我下载" for a named episode.
- Don't use for: YouTube/video podcasts (use yt-dlp, see `youtube-content`), bulk-archiving an entire feed.
- The usual follow-up IS transcription → a Chinese digest, and it is a separate step: hand off to an ASR skill (`mimo-asr`, `qwen-asr`, `stepaudio-asr`) — do not offer whisper as the default path. The digest deliverable shape the user expects is in `references/chinese-digest-format.md`.

## Prerequisites

- `curl`, `python3` (stdlib only), optional `ffprobe` for verification.
- Clash mixed proxy at `http://127.0.0.1:7897` — override with `--proxy` or `PODCAST_PROXY`; skip with `--no-proxy` when on another network.
- Reachability from CN: iTunes/Apple Podcasts API direct OK; anchor.fm + `*.cloudfront.net` audio NOT OK direct (CloudFront 403 region block).

## How to Run

```bash
python3 ~/.hermes/skills/media/podcast-download/scripts/podcast_download.py -q "Episode 244 The China Syndrome" -m "Episode 244"
```

Flags: `-q` search terms · `-m` regex pinning the episode title · `-o` outdir (default `~/Downloads`) · `--list` candidates only · `--force` re-download · `-f <rss>` / `-u <apple-url>` feed & URL modes.

Workflow: when the title is ambiguous run `--list` first and report the chosen `podcast — title` line back to the user; then run the download. The script probes direct → proxy, downloads with resume, checks `file` + ffprobe duration against feed metadata, writes `<name>.txt` show notes beside the audio, and prints the final `MEDIA:` line for delivery.

Give the terminal call `timeout=300`+; for files >100MB use `terminal(background=true, notify=true)` then poll.

| Need | Command |
|---|---|
| candidates only | `... -q "china syndrome" --list` |
| pin one episode | `... -q "<words>" -m "Episode 244"` |
| from a feed | `... -f <rss-url> -m "Episode 244"` |
| from Apple link | `... -u "https://podcasts.apple.com/.../id<show>?i=<episode>"` |

## Manual Fallback (script unavailable)

1. Identify via iTunes episode search (direct): `curl -s "https://itunes.apple.com/search?term=<urlencoded>&entity=podcastEpisode&limit=50"`; show feedUrl from `.../lookup?id=<collectionId>`.
2. Fetch the feed via proxy: `curl -sL -x http://127.0.0.1:7897 <feedUrl> -o /tmp/feed.rss` (anchor.fm times out direct).
3. `<enclosure url=...>` may wrap the real CDN mp3 (`d3ctxlq1ktw2nl.cloudfront.net/...`, percent-encoded — `curl -L` follows it).
4. Probe first: `curl -sIL -f -x http://127.0.0.1:7897 '<audio-url>'` — expect `content-type: audio/mpeg` + real `content-length`.
5. Download: `curl -sS -L -f -x http://127.0.0.1:7897 --retry 5 -C - -o out.mp3 '<audio-url>'` (~11 MB/s via proxy).
6. Verify with `ffprobe` (duration ≈ feed `itunes:duration` or `trackTimeMillis/1000`) and `file` (`MPEG ADTS … layer III`); deliver `MEDIA:<abs path>`.

## Pitfalls

- **curl exit 0 ≠ success.** Without `-f`, a CloudFront geo-block writes a ~986-byte HTML error page (`403 ERROR … The request could not be satisfied`) and exits 0. Always `-f` probes and check size/content-type before trusting a file.
- **A blocked transfer can stall with zero bytes** — no output file appears. If nothing lands in the outdir after ~30s, kill it and switch to the proxy.
- **Blocking is per edge POP**: direct from CN lands on a Singapore edge (403, `x-cache: Error from cloudfront`); via proxy it hits Hong Kong (200).
- **Same-title noise**: a guest-name query returns several of the podcast's OWN episodes from other years plus similarly-titled episodes from other shows — pin with `-m "Episode <N>"` and confirm the episode number, not just the show name; show the `podcast — title` line back to the user.
- **Feed metadata can drift** from the audio (re-uploads reuse the URL): trust ffprobe; use `--force` after a re-upload.

## Verification

- Exit 0 with `SAVED:` and `MEDIA:` lines; size ≈ 1 MB/min for 128 kbps mp3.
- `file` reports audio (`MPEG ADTS`, layer III); ffprobe duration within ~2 min of feed metadata.
- `<name>.txt` show notes exist next to the audio; those two paths are what you hand back to the user.
