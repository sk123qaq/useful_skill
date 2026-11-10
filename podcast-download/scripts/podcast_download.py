#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Find and download a podcast episode by title, Apple Podcasts link, or RSS feed.

China-network aware: probes the direct connection first (the iTunes API works
direct from CN), falls back to the local Clash proxy for geo-blocked hosts
(anchor.fm / Spotify / CloudFront audio: a direct request gets a CloudFront
403 "The request could not be satisfied" error page).

Examples:
  podcast_download.py -q "Episode 244 The China Syndrome"
  podcast_download.py -q "china syndrome" -m "Episode 244" --list
  podcast_download.py -f https://anchor.fm/s/e113880/podcast/rss -m "Episode 244"
  podcast_download.py -u "https://podcasts.apple.com/us/podcast/x/id1483677267?i=1000752249775"
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import quote, urlparse

DEFAULT_PROXY = os.environ.get("PODCAST_PROXY", "http://127.0.0.1:7897")
PROXY_FIRST_HOSTS = ("anchor.fm", "spotify.com", "spotifycdn.com")
AUDIO_EXTS = (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav")


def log(msg=""):
    print(msg, flush=True)


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def curl(url, proxy=None, max_time=90, head=False):
    """GET url (optionally via proxy); returns stdout on HTTP 2xx, else None. -f = fail on 4xx/5xx."""
    cmd = ["curl", "-sS", "-L", "-f", "--connect-timeout", "12", "--max-time", str(max_time)]
    if proxy:
        cmd += ["-x", proxy]
    if head:
        cmd.append("-I")
    cmd.append(url)
    r = run(cmd)
    return r.stdout if r.returncode == 0 else None


def fetch_text(url, proxy=None, prefer_proxy=False):
    """Fetch a text resource (feed / JSON). Returns (text, route-label) or (None, None)."""
    routes = [("proxy", proxy), ("direct", None)] if prefer_proxy else [("direct", None), ("proxy", proxy)]
    for label, p in routes:
        if label == "proxy" and not p:
            continue
        txt = curl(url, proxy=p, max_time=120)
        if txt and len(txt) > 200:
            return txt, label
    return None, None


def parse_duration(s):
    """'00:22:25' / '22:25' / '1345' -> seconds."""
    if not s:
        return 0
    s = s.strip()
    if s.isdigit():
        return int(s)
    parts = [int(p) for p in re.findall(r"\d+", s)]
    secs = 0
    for p in parts:
        secs = secs * 60 + p
    return secs


def episodes_from_itunes_results(data):
    out = []
    for r in data.get("results", []):
        if r.get("kind") != "podcast-episode" and r.get("wrapperType") != "podcastEpisode":
            continue
        out.append(dict(
            source="search",
            title=r.get("trackName", ""),
            podcast=r.get("collectionName", ""),
            date=r.get("releaseDate", ""),
            duration_s=(r.get("trackTimeMillis") or 0) // 1000,
            audio=r.get("episodeUrl", ""),
            feed=r.get("feedUrl", ""),
            page=r.get("trackViewUrl", ""),
            description=r.get("description", ""),
        ))
    return out


def itunes_search_episodes(query):
    url = "https://itunes.apple.com/search?term=" + quote(query) + "&entity=podcastEpisode&limit=50"
    txt, _ = fetch_text(url)
    if not txt:
        return []
    try:
        data = json.loads(txt)
    except json.JSONDecodeError:
        return []
    return episodes_from_itunes_results(data)


def parse_feed(xml):
    m_author = re.search(r"<itunes:author[^>]*>(.*?)</itunes:author>", xml, re.S)
    feed_author = html.unescape(m_author.group(1)).strip() if m_author else ""
    m_title = re.search(r"<channel[^>]*>.*?<title[^>]*>(.*?)</title>", xml, re.S)
    feed_title = html.unescape(m_title.group(1)).strip() if m_title else ""
    feed_name = feed_author or feed_title
    items = []
    for raw in re.findall(r"<item[\s>].*?</item>", xml, re.S):
        def grab(*tags):
            for t in tags:
                m = re.search(r"<" + t + r"[^>]*>(.*?)</" + t + r">", raw, re.S)
                if m:
                    v = html.unescape(m.group(1)).strip()
                    v = re.sub(r"^<!\[CDATA\[(.*?)\]\]>$", r"\1", v, flags=re.S).strip()
                    if v:
                        return v
            return ""

        enc = re.search(r'<(?:enclosure|media:content)[^>]*?\burl="([^"]+)"', raw)
        items.append(dict(
            source="feed",
            title=grab("title"),
            podcast=grab("itunes:author") or feed_name,
            date=grab("pubDate"),
            duration_s=parse_duration(grab("itunes:duration")),
            audio=html.unescape(enc.group(1)) if enc else "",
            feed="",
            page=grab("link"),
            description=grab("itunes:summary", "itunes:description", "description"),
        ))
    return [i for i in items if i["title"]]


def select(items, match=None, query=None):
    if match:
        rx = re.compile(match, re.I)
        hit = [i for i in items if rx.search(i["title"])]
    elif query:
        toks = re.findall(r"[a-z0-9]+", query.lower())
        hit = [i for i in items if all(t in i["title"].lower() for t in toks)]
    else:
        hit = list(items)
    if not hit:
        return None
    if hit[0]["source"] == "search":
        hit.sort(key=lambda i: i.get("date") or "", reverse=True)
    return hit[0]


def probe(url, proxy=None):
    """Return response text if url serves a real file on this route, else None."""
    base = ["curl", "-sS", "-L", "-f", "--connect-timeout", "12", "--max-time", "30"]
    if proxy:
        base += ["-x", proxy]
    r = run(base + ["-I", url])
    if r.returncode == 0 and r.stdout:
        return r.stdout
    r = run(base + ["-r", "0-1023", "-o", "/dev/null",
                    "-w", "status=%{http_code} type=%{content_type}", url])
    if r.returncode == 0:
        return r.stdout
    return None


def download(url, out_path, proxy, label):
    cmd = ["curl", "-sS", "-L", "-f", "--retry", "5", "--retry-delay", "2",
           "--connect-timeout", "15", "--max-time", "1800", "-C", "-", "-o", out_path]
    if proxy:
        cmd += ["-x", proxy]
    cmd += ["-w", "http=%{http_code} bytes=%{size_download} time=%{time_total}s speed=%{speed_download}B/s", url]
    log("downloading via %s: %s" % (label, url))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        log("curl failed (exit %s)" % r.returncode)
        return False
    return True


def sanitize(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    return name[:180] or "episode"


def show(items, n=25):
    if not items:
        log("(no items)")
        return
    for i, it in enumerate(items[:n], 1):
        log("%2d. %s | %s | %s%s" % (i, it["podcast"] or "?", it["title"], it["date"], "" if it["audio"] else " | NO AUDIO URL"))


def main():
    ap = argparse.ArgumentParser(description="Find and download a podcast episode.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("-q", "--query", help="search terms (e.g. 'Episode 244 The China Syndrome')")
    src.add_argument("-f", "--feed", help="RSS feed URL")
    src.add_argument("-u", "--url", help="Apple Podcasts URL (show or episode) or RSS URL")
    ap.add_argument("-m", "--match", help="regex selecting the episode title (e.g. 'Episode 244')")
    ap.add_argument("--list", action="store_true", help="only list candidates, do not download")
    ap.add_argument("-o", "--outdir", default=os.path.expanduser("~/Downloads"))
    ap.add_argument("--proxy", default=DEFAULT_PROXY, help="HTTP proxy for geo-blocked hosts")
    ap.add_argument("--no-proxy", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-download even if file exists")
    args = ap.parse_args()
    proxy = None if args.no_proxy else (args.proxy or None)

    items = []
    if args.query:
        items = itunes_search_episodes(args.query)
        if not items:
            log("ERROR: no episodes found for query")
            sys.exit(2)
    else:
        feed_url = args.feed or args.url or ""
        if "podcasts.apple.com" in feed_url and "id" in feed_url:
            m_show = re.search(r"/id(\d+)", feed_url)
            m_ep = re.search(r"[?&]i=(\d+)", feed_url)
            if m_ep:
                txt, _ = fetch_text("https://itunes.apple.com/lookup?id=" + m_ep.group(1))
                if txt:
                    try:
                        items = episodes_from_itunes_results(json.loads(txt))
                    except json.JSONDecodeError:
                        pass
            if not items and m_show:
                txt, _ = fetch_text("https://itunes.apple.com/lookup?id=%s&entity=podcastEpisode&limit=200" % m_show.group(1))
                if txt:
                    try:
                        items = episodes_from_itunes_results(json.loads(txt))
                    except json.JSONDecodeError:
                        pass
            if not items:
                log("ERROR: could not resolve Apple Podcasts URL")
                sys.exit(2)
            if not m_ep and items and items[0].get("feed"):
                feed_url = items[0]["feed"]
                items = []
        if not items:
            if "podcasts.apple.com" in feed_url:
                log("ERROR: could not resolve Apple Podcasts URL")
                sys.exit(2)
            prefer = any(h in feed_url for h in PROXY_FIRST_HOSTS)
            xml, label = fetch_text(feed_url, proxy=proxy, prefer_proxy=prefer)
            if not xml:
                log("ERROR: could not fetch feed (tried direct and proxy)")
                sys.exit(2)
            log("feed fetched (%s), parsing ..." % label)
            items = parse_feed(xml)
            if not items:
                log("ERROR: feed parsed but no items found")
                sys.exit(2)
        if not args.match and args.url and not args.feed:
            # single-episode Apple URL already pinned; else leave match None (feed = newest first)
            pass

    if args.list:
        show(items)
        sys.exit(0)

    chosen = select(items, match=args.match, query=(args.query if not args.match else None))
    if not chosen:
        log("no matching episode; nearest candidates:")
        show(items[:15])
        sys.exit(3)
    log("selected: %s — %s  [%s]" % (chosen["podcast"] or "?", chosen["title"], chosen["date"]))

    # Enrich search-sourced picks with fuller feed metadata (duration, description).
    if chosen["source"] == "search" and chosen.get("feed"):
        prefer = any(h in chosen["feed"] for h in PROXY_FIRST_HOSTS)
        xml, _ = fetch_text(chosen["feed"], proxy=proxy, prefer_proxy=prefer)
        if xml:
            same = [i for i in parse_feed(xml) if i["title"] == chosen["title"]]
            if same:
                for k in ("description", "duration_s", "audio", "date", "page"):
                    if same[0].get(k):
                        chosen[k] = same[0][k]

    if not chosen["audio"]:
        log("ERROR: no audio URL for selected episode")
        sys.exit(4)

    ext = os.path.splitext(urlparse(chosen["audio"]).path)[1].lower()
    if ext not in AUDIO_EXTS:
        ext = ".mp3"
    base = "%s - %s" % (chosen["podcast"], chosen["title"]) if chosen["podcast"] else chosen["title"]
    outdir = os.path.expanduser(args.outdir)
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, sanitize(base) + ext)

    if os.path.exists(out) and not args.force and os.path.getsize(out) > 200_000:
        log("already downloaded: %s" % out)
        _summarize(out, chosen)
        return

    routes = []
    if probe(chosen["audio"], proxy=None) is not None:
        routes.append((None, "direct"))
    elif proxy and probe(chosen["audio"], proxy=proxy) is not None:
        routes.append((proxy, "proxy"))
    else:
        log("ERROR: audio URL unreachable (tried direct%s)" % (" and proxy" if proxy else "; no proxy configured"))
        sys.exit(4)

    if routes[0][1] == "proxy" and not args.no_proxy:
        routes.append((None, "direct"))  # last-ditch alternative route
    elif proxy:
        routes.append((proxy, "proxy"))

    ok = False
    for p, label in routes:
        if download(chosen["audio"], out, p, label):
            ok = True
            break
    if not ok or not os.path.exists(out):
        log("ERROR: download failed on all routes")
        sys.exit(5)

    _summarize(out, chosen)


def _summarize(out, chosen):
    size = os.path.getsize(out)
    log("")
    log("SAVED: %s" % out)
    log("size: %.1f MB" % (size / 1048576.0))
    r = run(["file", "-b", out])
    if r.stdout.strip():
        log("type: %s" % r.stdout.strip())
    dur = None
    if shutil.which("ffprobe"):
        r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", out])
        try:
            dur = float(r.stdout.strip())
        except ValueError:
            pass
    if dur:
        log("duration: %d:%02d" % (dur // 60, int(dur) % 60))
        if chosen.get("duration_s") and abs(dur - chosen["duration_s"]) > 120:
            log("WARNING: duration differs from feed metadata (%ss)" % chosen["duration_s"])

    notes = os.path.splitext(out)[0] + ".txt"
    with open(notes, "w", encoding="utf-8") as fh:
        fh.write("%s\n%s\n\n" % (chosen["title"], chosen["podcast"]))
        if chosen.get("date"):
            fh.write("date: %s\n" % chosen["date"])
        if dur:
            fh.write("duration: %d:%02d\n" % (dur // 60, int(dur) % 60))
        if chosen.get("page"):
            fh.write("page: %s\n" % chosen["page"])
        if chosen.get("feed"):
            fh.write("feed: %s\n" % chosen["feed"])
        fh.write("audio: %s\n\n" % chosen["audio"])
        desc = re.sub(r"<[^>]+>", "\n", chosen.get("description") or "")
        desc = re.sub(r"\n{2,}", "\n", html.unescape(desc)).strip()
        if desc:
            fh.write("show notes:\n%s\n" % desc)
    log("shownotes: %s" % notes)
    log("")
    log("deliver with: MEDIA:%s" % out)


if __name__ == "__main__":
    main()
