#!/bin/sh
# Runs the app as an unprivileged user whose uid/gid can be set with PUID/PGID (default 1000),
# so files created in the /data bind mount belong to the host user instead of root.
set -e
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
if [ "$(id -u)" = "0" ]; then
    if [ "$(id -g app)" != "$PGID" ]; then groupmod -o -g "$PGID" app; fi
    if [ "$(id -u app)" != "$PUID" ]; then usermod -o -u "$PUID" app; fi
    mkdir -p /data
    chown app:app /data
    # Fix ownership of data created by older (root) versions of the image. Cheap when already correct.
    if find /data ! -user app -print -quit 2>/dev/null | grep -q .; then chown -R app:app /data; fi
    exec gosu app "$0" "$@"
fi
# A self-signed certificate for the HTTPS listener (phones need HTTPS for the microphone). Bring your own
# cert.pem/key.pem into /data/tls to replace it.
TLS_DIR="${TLS_DIR:-/data/tls}"
if [ ! -s "$TLS_DIR/cert.pem" ] || [ ! -s "$TLS_DIR/key.pem" ]; then
    mkdir -p "$TLS_DIR"
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=voice-trainer" \
        -addext "subjectAltName=DNS:voice-trainer,DNS:localhost,IP:127.0.0.1" \
        -keyout "$TLS_DIR/key.pem" -out "$TLS_DIR/cert.pem" >/dev/null 2>&1 || echo "warning: could not create a TLS certificate, HTTPS is off"
fi
exec "$@"
