# Telegram Video Downloader Bot

Python 3.12 · aiogram 3 · yt-dlp · FFmpeg · asyncio · SQLite · Docker

Paste a link from **TikTok, Instagram, YouTube (incl. Shorts), Facebook or X (Twitter)**, pick a quality
(**360p – 1080p** or **MP3**) from inline buttons, watch live progress, and get the file uploaded back to Telegram.

## Features

| Area | Details |
|---|---|
| Platforms | TikTok, Instagram Reels/posts, YouTube videos + Shorts, Facebook, X (Twitter). Other yt-dlp sites via `EXTRA_DOMAINS`. |
| No watermark | TikTok: the variant marked "watermarked" is never selected when an original stream exists. |
| Quality | Inline buttons for 1080p / 720p / 480p / 360p + MP3, with estimated file size and a ⚠️ when it exceeds Telegram's limit. Vertical videos are ranked by their short side. |
| Progress | Live bar with percent, speed, ETA for download → processing → upload. Cancel button. |
| Compatibility | Non-H.264/AAC output is remuxed or transcoded with FFmpeg so it plays inline in Telegram. |
| Limits | Upload-size check (50 MB cloud API, 2000 MB with a local Bot API server), max duration, timeouts, per-user single job, global concurrency, daily quota, flood control. |
| Private videos | Users upload **their own** `cookies.txt` (`/cookies`) for content they are allowed to see. Stored per user (mode 600), deletable with `/delcookies`. |
| Admin | `/admin` panel: statistics, user lists, `/ban`, `/unban`, `/user`, and **broadcast** (any message type, preview + confirm, live counters, blocked-user detection). |
| Hygiene | Every job runs in its own temp dir that is always deleted; leftovers are purged at startup and every 10 min. |
| Security | Domain allow-list + generic extractor disabled (no SSRF to internal addresses); runs as non-root; full URLs are never stored. |

## Project layout

```
bot/
  main.py            wiring, startup, graceful shutdown
  config.py          env-based configuration
  downloader.py      yt-dlp + FFmpeg pipeline, timeouts, cancel, cleanup
  formats.py         platform allow-list + quality selection (pure, unit-tested)
  progress.py        progress state + periodic Telegram updates
  upload.py          upload with byte-level progress
  db.py              SQLite: users, download log, statistics
  keyboards.py       inline keyboards
  texts.py           every user-facing string (edit/translate here)
  errors.py          error types + friendly yt-dlp error mapping
  middlewares.py     user registration, ban check, flood control
  handlers/user.py   links, quality buttons, download & upload
  handlers/cookies.py  private-video cookies
  handlers/admin.py  admin panel, stats, broadcast
tests/test_formats.py
```

## 1. Create the bot

1. Talk to **@BotFather** → `/newbot` → copy the token.
2. Get your numeric Telegram ID (e.g. from **@userinfobot**) — this becomes your admin ID.

## 2. Deploy on a VPS with Docker (recommended)

Any Ubuntu/Debian VPS with 1 GB+ RAM works.

```bash
# Install Docker (once)
curl -fsSL https://get.docker.com | sh

# Get the project onto the server (git clone, or scp the folder), then:
cd tgvideobot
cp .env.example .env
nano .env                 # set BOT_TOKEN, ADMIN_IDS, TELEGRAM_API_ID, TELEGRAM_API_HASH

mkdir -p data && sudo chown 1000:1000 data    # the container runs as uid 1000
docker compose run --rm --no-deps bot python -m bot.logout   # once: see section 5
docker compose up -d --build
docker compose logs -f bot                    # should print "Started @yourbot"
```

Common operations:

```bash
docker compose restart bot                 # restart (also upgrades yt-dlp when AUTO_UPDATE_YTDLP=1)
docker compose up -d --build               # deploy code changes
docker compose logs --tail=100 bot         # logs
docker compose down                        # stop
cp data/bot.sqlite3 backup-$(date +%F).db  # back up users & stats
```

## 3. Run without Docker (development)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
sudo apt install ffmpeg            # FFmpeg and ffprobe must be on PATH
pip install -r requirements.txt
cp .env.example .env && nano .env
python -m bot
```

Run the unit tests (no extra packages needed): `python -m unittest discover -s tests -v`

## 4. Configuration (`.env`)

See `.env.example` for every option. The important ones:

| Variable | Default | Meaning |
|---|---|---|
| `BOT_TOKEN` | – | Required. |
| `ADMIN_IDS` | – | Comma-separated admin user IDs. |
| `MAX_HEIGHT` | 1080 | Highest quality offered. |
| `MAX_DURATION_MIN` | 60 | Longest video accepted. |
| `MAX_CONCURRENT_DOWNLOADS` | 3 | Parallel jobs; extra jobs wait in a queue. |
| `DAILY_LIMIT` | 30 | Downloads per user per 24 h (0 = unlimited; admins exempt). |
| `DOWNLOAD_TIMEOUT` / `UPLOAD_TIMEOUT` | 600 / 900 | Seconds. |
| `PROXY_URL` | – | Proxy if a platform blocks your VPS IP. |
| `COOKIES_FILE` | – | Operator cookies; **admins only** unless `PUBLIC_COOKIES=true`. |
| `BOT_API_URL` | – | Local Bot API server (lifts the 50 MB cap). |

## 5. Uploads up to 2 GB

Telegram's cloud Bot API caps bot uploads at **50 MB**. This project therefore ships with a **local Bot API server**
(`telegram-bot-api` service in `docker-compose.yml`) that raises the limit to **2000 MB**. It is enabled by default.

One-time setup:

1. Create an app at <https://my.telegram.org> → *API development tools* and copy `api_id` / `api_hash`.
2. Put them in `.env` as `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`.
3. Detach the bot from the cloud API (needed once):
   `docker compose run --rm --no-deps bot python -m bot.logout`
4. Start everything: `docker compose up -d --build`
   (if the bot can't log in right away, wait ~10 minutes and `docker compose restart bot`).

Things to plan for with big files:

- **Disk:** a 2 GB video can need about 2x that while merging. Keep 10+ GB free and keep
  `MAX_CONCURRENT_DOWNLOADS` low (2 is the default).
- **Time:** timeouts default to 60 min download / 2 h upload in this mode (`DOWNLOAD_TIMEOUT`, `UPLOAD_TIMEOUT`).
- **Length cap:** `MAX_DURATION_MIN` (default 60) still applies; raise it if you really need longer videos.
- To go back to the plain 50 MB cloud mode, remove the `telegram-bot-api` service and the `BOT_API_URL` /
  `MAX_UPLOAD_MB` lines from the compose file.

## 6. Using the bot

- **User:** `/start`, paste a link, tap a quality. `/mystats`, `/cookies`, `/delcookies`, `/help`.
- **Admin:** `/admin` (panel), `/stats`, `/broadcast`, `/ban <id>`, `/unban <id>`, `/user <id>`.

### Private / login-only videos

A user who legitimately has access (own account, content shared with them) exports their browser cookies as
a Netscape `cookies.txt` (any "cookies.txt" browser extension), sends `/cookies`, and uploads the file.
The bot saves it privately for that user only, deletes the upload message, and uses it only for that user's downloads.
Cookies act like a password: use your own account only, and `/delcookies` when done.

## Troubleshooting

- **YouTube says "Sign in to confirm you're not a bot"** — datacenter IPs are often challenged. Provide cookies
  (`COOKIES_FILE` for admins), use `PROXY_URL`, and keep yt-dlp current (`docker compose restart bot`).
- **A platform suddenly stops working** — upgrade yt-dlp (restart with `AUTO_UPDATE_YTDLP=1`, or rebuild).
- **"File too big"** — pick a lower quality or MP3, or enable the local Bot API server (section 5).
- **Permission errors on `data/`** — `sudo chown -R 1000:1000 data`.
- **Instagram/Facebook fail without login** — those platforms often require an account; use `/cookies`.

## Responsible use

Download only content you own, have permission to save, or that the platform's terms and your local law allow.
Re-uploading other people's videos can infringe copyright. The "no watermark" feature selects the clean stream
a platform itself provides; it does not edit or remove marks from videos. You are responsible for how your bot
instance is used — consider keeping it private with `ALLOWED` admins, a low `DAILY_LIMIT`, and the ban tools.
