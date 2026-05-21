"""Entry point for `python -m voce` and the `voce` CLI command."""
import argparse

import uvicorn

from voce.config import settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Voce — personal Quanta Magazine TTS companion"
    )
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--log-level", default=settings.log_level.lower())
    args = parser.parse_args()
    print(f"Voce is listening at http://{args.host}:{args.port}")
    uvicorn.run(
        "voce.api:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
