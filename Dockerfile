FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

# Deno: recent yt-dlp versions use a JavaScript runtime for full YouTube support.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

RUN useradd --create-home --uid 1000 bot
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bot ./bot
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p /app/data && chown -R bot:bot /app

USER bot
ENV DATA_DIR=/app/data
VOLUME ["/app/data"]

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "bot"]
