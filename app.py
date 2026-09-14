#!/usr/bin/env python
"""Start the Pixel-Perfect web service.

    uv run app.py                 # http://127.0.0.1:8000  (localhost only)
    uv run app.py --port 9000 --reload

Thin launcher around the FastAPI app in ``pixelperfect.web.api``. ``app`` is
also exported so process managers can target ``app:app`` directly.

SECURITY: the default bind is 127.0.0.1 (localhost) on purpose. The service is
unauthenticated and compute-intensive. Only set ``HOST=0.0.0.0`` (bind to all
interfaces) behind a reverse proxy that provides TLS, authentication, and rate
limiting. See SECURITY.md before exposing it to any network.
"""

from __future__ import annotations

import argparse
import os
import sys

# Allow running straight from a source checkout without installing.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from pixelperfect.web.api import app  # noqa: E402  (re-exported for `app:app`)


def main() -> None:
    p = argparse.ArgumentParser(description="Run the Pixel-Perfect web service.")
    p.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    p.add_argument("--reload", action="store_true", help="Auto-reload on code changes (dev).")
    args = p.parse_args()

    import uvicorn

    print(f"Pixel-Perfect → http://{args.host}:{args.port}")
    # Pass an import string when reloading so uvicorn can re-import on change.
    target = "pixelperfect.web.api:app" if args.reload else app
    uvicorn.run(target, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
