#!/bin/sh
set -e

# Video sites change constantly; an up-to-date yt-dlp is the #1 fix for "it stopped working".
if [ "${AUTO_UPDATE_YTDLP:-1}" = "1" ]; then
    echo "Updating yt-dlp..."
    python -m pip install --user --quiet --upgrade "yt-dlp[default]" || echo "yt-dlp update failed, using bundled version"
fi

exec "$@"
