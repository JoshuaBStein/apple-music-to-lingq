#!/usr/bin/env python3
"""
LyricLingQ — Apple Music → Lyrics → LingQ
A macOS menu bar app that grabs the currently playing Apple Music track,
fetches its lyrics, and imports them as a lesson in your LingQ library.
"""

import os
import re
import subprocess
import threading
import urllib.parse

import requests
import rumps
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────────
LINGQ_API_KEY  = os.environ["LINGQ_API_KEY"]
LINGQ_LANGUAGE = os.getenv("LINGQ_LANGUAGE", "he")

# Get a free Genius token at: https://genius.com/api-clients
# Leave blank in .env to skip Genius and only try Lyrics.ovh
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY", "")
# ──────────────────────────────────────────────────────────────────────────────

# Strips " (Prod. by ...)", " [feat. ...]", etc. from titles before searching
_PARENS_RE = re.compile(r'\s*[\(\[].*?[\)\]]', re.UNICODE)


def clean_title(title: str) -> str:
    cleaned = _PARENS_RE.sub("", title).strip()
    return cleaned if cleaned else title


def get_apple_music_track() -> tuple[str, str] | None:
    """Return (title, artist) of the currently playing Apple Music track, or None."""
    script = '''
    tell application "Music"
        if player state is playing then
            set trackName to name of current track
            set artistName to artist of current track
            return trackName & "|||" & artistName
        else
            return "NOT_PLAYING"
        end if
    end tell
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    output = result.stdout.strip()
    if output == "NOT_PLAYING" or not output:
        return None
    parts = output.split("|||")
    if len(parts) != 2:
        return None
    return parts[0].strip(), parts[1].strip()


def fetch_lyrics_ovh(title: str, artist: str) -> str | None:
    encoded_artist = urllib.parse.quote(artist)
    encoded_title  = urllib.parse.quote(title)
    url = f"https://api.lyrics.ovh/v1/{encoded_artist}/{encoded_title}"
    print(f"  [Lyrics.ovh] GET {url}")
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        lyrics = resp.json().get("lyrics", "").strip()
        return lyrics if lyrics else None
    except Exception as e:
        print(f"  [Lyrics.ovh] Error: {e}")
        return None


def fetch_lyrics_genius(title: str, artist: str) -> str | None:
    if not GENIUS_API_KEY:
        return None
    query = f"{artist} {title}"
    print(f"  [Genius] Searching: {query!r}")
    headers = {"Authorization": f"Bearer {GENIUS_API_KEY}"}
    try:
        search_resp = requests.get(
            "https://api.genius.com/search",
            headers=headers,
            params={"q": query},
            timeout=10,
        )
        if search_resp.status_code == 401:
            print("  [Genius] 401 Unauthorized — API key is invalid or expired.")
            print("  [Genius] Get a new key at: https://genius.com/api-clients")
            return None
        search_resp.raise_for_status()
        hits = search_resp.json().get("response", {}).get("hits", [])
        if not hits:
            print("  [Genius] No hits found.")
            return None

        song_url = hits[0]["result"]["url"]
        print(f"  [Genius] Scraping: {song_url}")
        page = requests.get(song_url, timeout=10)
        soup = BeautifulSoup(page.text, "html.parser")

        # Genius wraps lyrics in containers with data-lyrics-container attribute
        containers = soup.find_all("div", attrs={"data-lyrics-container": "true"})
        if not containers:
            print("  [Genius] Could not find lyrics container on page.")
            return None

        lines = []
        for container in containers:
            for br in container.find_all("br"):
                br.replace_with("\n")
            lines.append(container.get_text())

        lyrics = "\n".join(lines).strip()
        return lyrics if lyrics else None
    except Exception as e:
        print(f"  [Genius] Error: {e}")
        return None


def fetch_lyrics_shironet(title: str, artist: str) -> str | None:
    """Scrape lyrics from Shironet — the primary Hebrew lyrics database."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    try:
        # Visit homepage first — required to receive cookies that bypass bot protection
        session.get("https://shironet.mako.co.il/", timeout=10)
    except Exception:
        pass

    # Try artist+title first; fall back to title alone (handles English artist names
    # that don't match Shironet's Hebrew artist index).
    queries = [f"{artist} {title}", title]
    try:
        for query in queries:
            print(f"  [Shironet] Searching: {query!r}")
            resp = session.get(
                "https://shironet.mako.co.il/searchSongs",
                params={"act": "search", "q": query, "type": "lyrics"},
                timeout=10,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Skip the auto-play duplicate links ("play=true")
            all_song_links = soup.find_all("a", href=re.compile(r"/artist\?type=lyrics"))
            link = next((l for l in all_song_links if "play=true" not in l["href"]), None)
            if not link:
                print("  [Shironet] No results found.")
                continue

            song_url = "https://shironet.mako.co.il" + link["href"]
            print(f"  [Shironet] Fetching: {song_url}")
            page = session.get(song_url, timeout=10)
            soup = BeautifulSoup(page.text, "html.parser")

            lyrics_el = (
                soup.find(attrs={"class": "artist_lyrics_text"})
                or soup.find(attrs={"itemprop": re.compile(r"^lyrics$", re.I)})
            )
            if not lyrics_el:
                print("  [Shironet] Could not find lyrics container on page.")
                continue

            for br in lyrics_el.find_all("br"):
                br.replace_with("\n")
            lyrics = lyrics_el.get_text().strip()
            if lyrics:
                return lyrics
        return None
    except Exception as e:
        print(f"  [Shironet] Error: {e}")
        return None


def fetch_lyrics(title: str, artist: str) -> str | None:
    """Try Lyrics.ovh first (cleaned title), then fall back to Genius."""
    clean = clean_title(title)
    if clean != title:
        print(f"[Lyrics] Cleaned title: {title!r} → {clean!r}")

    # 1. Lyrics.ovh with cleaned title
    lyrics = fetch_lyrics_ovh(clean, artist)
    if lyrics:
        print(f"[Lyrics] Got {len(lyrics)} chars from Lyrics.ovh")
        return lyrics

    # 2. Genius fallback
    if GENIUS_API_KEY:
        print("[Lyrics] Trying Genius fallback…")
        lyrics = fetch_lyrics_genius(clean, artist)
        if lyrics:
            print(f"[Lyrics] Got {len(lyrics)} chars from Genius")
            return lyrics

    # 3. Shironet fallback (Hebrew lyrics database)
    print("[Lyrics] Trying Shironet fallback…")
    lyrics = fetch_lyrics_shironet(clean, artist)
    if lyrics:
        print(f"[Lyrics] Got {len(lyrics)} chars from Shironet")
        return lyrics

    print("[Lyrics] All sources exhausted — no lyrics found.")
    return None


def create_lingq_lesson(title: str, text: str) -> tuple[bool, str]:
    """POST a new standalone lesson to LingQ via the v3 Lessons API."""
    url = f"https://www.lingq.com/api/v3/{LINGQ_LANGUAGE}/lessons/"
    headers = {
        "Authorization": f"Token {LINGQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "title": title,
        "text":  text,
        "tags":  ["LyricLingQ"],
    }
    print(f"[LingQ] POSTing to: {url}")
    print(f"[LingQ] Lesson title: {title}")
    print(f"[LingQ] Lyrics length: {len(text)} chars")
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        print(f"[LingQ] Response status: {resp.status_code}")
        print(f"[LingQ] Response body:   {resp.text[:300]}")
        if resp.status_code in (200, 201):
            data = resp.json()
            lesson_ref = data.get("url") or data.get("id") or "(see LingQ library)"
            return True, str(lesson_ref)
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except requests.exceptions.ConnectionError:
        return False, "No internet connection."
    except requests.exceptions.Timeout:
        return False, "Request timed out."
    except Exception as e:
        return False, str(e)


class LyricLingQApp(rumps.App):

    def __init__(self):
        super().__init__("♪", quit_button="Quit")
        self.menu = [
            rumps.MenuItem("Import Current Song → LingQ", callback=self.import_song),
            None,
            rumps.MenuItem(f"Language: {LINGQ_LANGUAGE.upper()}", callback=None),
        ]
        self.menu[f"Language: {LINGQ_LANGUAGE.upper()}"].set_callback(None)

    def import_song(self, _):
        threading.Thread(target=self._do_import, daemon=True).start()

    def _do_import(self):
        print("\n─── Import triggered ───────────────────────────────")

        print("[Apple Music] Querying current track via AppleScript…")
        track = get_apple_music_track()
        if not track:
            print("[Apple Music] Nothing playing or Music.app not running.")
            rumps.notification(
                title="LyricLingQ",
                subtitle="Nothing playing",
                message="Play a track in Apple Music and try again.",
            )
            return

        title, artist = track
        print(f"[Apple Music] Now playing: {title} — {artist}")
        rumps.notification(
            title="LyricLingQ",
            subtitle="Fetching lyrics…",
            message=f"{title} — {artist}",
        )

        lyrics = fetch_lyrics(title, artist)
        if not lyrics:
            rumps.notification(
                title="LyricLingQ",
                subtitle="Lyrics not found",
                message=f'No lyrics found for "{clean_title(title)}" by {artist}.',
            )
            return

        lesson_title = f"{clean_title(title)} — {artist}"
        print(f"[LingQ] Creating lesson: {lesson_title}")
        success, msg = create_lingq_lesson(lesson_title, lyrics)

        if success:
            print(f"[LingQ] Success! Ref: {msg}")
            rumps.notification(
                title="LyricLingQ — Imported!",
                subtitle=lesson_title,
                message=f'Added to your {LINGQ_LANGUAGE.upper()} library on LingQ.',
            )
        else:
            print(f"[LingQ] Failed: {msg}")
            rumps.notification(
                title="LyricLingQ — Failed",
                subtitle="LingQ import error",
                message=msg,
            )
        print("─────────────────────────────────────────────────────\n")


if __name__ == "__main__":
    print(f"LyricLingQ starting — language: {LINGQ_LANGUAGE.upper()}")
    genius_status = "configured" if GENIUS_API_KEY else "not set (Lyrics.ovh only)"
    print(f"Genius API key: {genius_status}")
    print("Click the ♪ menu bar icon to import the current song.\n")
    LyricLingQApp().run()
