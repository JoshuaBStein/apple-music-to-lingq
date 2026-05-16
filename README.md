# LyricLingQ

A macOS menu bar app that grabs the currently playing Apple Music track, fetches its lyrics, and imports them as a lesson in your LingQ library — one click.

## How it works

1. Play a song in Apple Music
2. Click **♪** in the menu bar → **Import Current Song → LingQ**
3. The app fetches lyrics from [Lyrics.ovh](https://lyricsovh.docs.apiary.io/) (free, no key needed)
4. Creates a private lesson in your LingQ account under your configured language

## Requirements

- macOS (uses AppleScript to talk to Music.app)
- Python 3.10+
- Apple Music desktop app
- A [LingQ account](https://www.lingq.com) with an API key

## Setup

```bash
# 1. Clone or download this repo, then enter the directory
cd AppleMusicLyricGrabber

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

## Configuration

Open `lyric_lingq.py` and set the two constants near the top:

```python
LINGQ_API_KEY  = "YOUR_LINGQ_API_KEY"   # https://www.lingq.com/accounts/apikey/
LINGQ_LANGUAGE = "es"                   # your target language code
```

Common language codes: `es` Spanish · `fr` French · `de` German · `it` Italian · `pt` Portuguese · `ja` Japanese · `ko` Korean · `zh` Chinese

## Running

```bash
source venv/bin/activate
python3 lyric_lingq.py
```

A `♪` icon appears in your macOS menu bar. Keep the terminal window open (or run it as a background process).

### Run in the background

```bash
nohup python3 lyric_lingq.py &> lyric_lingq.log &
```

## Permissions

On first run, macOS will ask if Terminal (or your shell) can control Music.app. Click **OK** — this is required for the AppleScript lookup.

## Limitations

- Lyrics.ovh coverage is good for popular tracks but may miss obscure songs
- Lyrics are not language-filtered — confirm the song is in your target language before importing
- LingQ lessons are created as **private** by default

## Dependencies

| Package | Purpose |
|---|---|
| `rumps` | macOS menu bar app framework |
| `requests` | HTTP calls to Lyrics.ovh and LingQ API |
