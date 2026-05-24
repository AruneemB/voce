"""Entry point for `python -m voce` and the `voce` CLI command."""
import argparse
import sys
import webbrowser

import uvicorn
from loguru import logger

from voce.cache import sweep_expired_cache
from voce.config import settings
from voce.db import get_connection
from voce.feeds import refresh_all_feeds


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Voce — personal Quanta Magazine TTS companion"
    )
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--log-level", default=settings.log_level.lower())
    parser.add_argument(
        "--refresh-now",
        action="store_true",
        help="Fetch all feeds and print results, then exit without starting the server.",
    )
    parser.add_argument(
        "--sweep-cache",
        action="store_true",
        help="Delete expired audio cache entries and exit without starting the server.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open a browser window after starting the server.",
    )
    args = parser.parse_args()

    if args.refresh_now:
        conn = get_connection()
        result = refresh_all_feeds(conn)
        conn.close()
        print(result)
        raise SystemExit(0)

    if args.sweep_cache:
        conn = get_connection()
        count = sweep_expired_cache(conn)
        conn.close()
        print(f"Swept {count} expired cache entries.")
        raise SystemExit(0)

    logger.remove()
    logger.add(
        sys.stderr,
        level=args.log_level.upper(),
        format="{time:HH:mm:ss} {level: <7} {module}: {message}",
    )
    logger.add("data/voce.log", rotation="10 MB", retention="7 days", level="DEBUG")

    print(f"Voce is listening at http://{args.host}:{args.port}")
    if not args.no_browser:
        webbrowser.open(f"http://{args.host}:{args.port}")
    uvicorn.run(
        "voce.api:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
