"""Serves the app over HTTP and, when a certificate is present, over HTTPS as well - in one process.

Browsers allow the microphone only on localhost or over HTTPS, so a phone on the LAN needs the TLS port.
The entrypoint creates a self-signed certificate in /data/tls; the phone shows a warning once. Two separate
server processes would each have their own job manager, so both listeners share this one application.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import uvicorn

from .config import DATA_DIR
from .main import app

HTTP_PORT = int(os.environ.get("HTTP_PORT", "8000"))
HTTPS_PORT = int(os.environ.get("HTTPS_PORT", "8443"))
TLS_DIR = Path(os.environ.get("TLS_DIR", str(DATA_DIR / "tls")))


async def serve() -> None:
    servers = [uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=HTTP_PORT, log_level="info"))]
    cert, key = TLS_DIR / "cert.pem", TLS_DIR / "key.pem"
    if cert.exists() and key.exists():
        servers.append(uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=HTTPS_PORT, log_level="info", ssl_certfile=str(cert), ssl_keyfile=str(key))))
    # only one of them may react to SIGTERM/SIGINT; the other is stopped alongside
    for extra in servers[1:]:
        extra.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    tasks = [asyncio.create_task(s.serve()) for s in servers]
    await tasks[0]
    for s in servers[1:]:
        s.should_exit = True
    await asyncio.gather(*tasks[1:], return_exceptions=True)


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
