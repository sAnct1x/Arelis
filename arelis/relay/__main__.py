"""Run the mailbox: python -m arelis.relay

The PC installer ships the client. This process is what you put on a small
host with a public HTTPS reverse proxy. Users never run it.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading

from arelis.relay.config import load_relay_settings
from arelis.relay.server import run_relay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Arelis mailbox (operator).")
    parser.add_argument("--host", default=os.environ.get("ARELIS_RELAY_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("ARELIS_RELAY_PORT", "8787")),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = load_relay_settings()
    token = (os.environ.get("ARELIS_RELAY_TOKEN") or settings.token).strip()
    if not token:
        print(
            "Set ARELIS_RELAY_TOKEN or sms.relay_token in data/secrets.yaml.",
            file=sys.stderr,
        )
        return 2
    httpd = run_relay(args.host, args.port, token)
    logging.info("Listening. Ctrl+C to stop.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
