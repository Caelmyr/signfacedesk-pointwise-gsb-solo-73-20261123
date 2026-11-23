"""Serve the sign-face survey desk and its local image preparation tool."""
import os
from pathlib import Path

from waitress import serve

from image_lab import create_app

from .web import install


def application(data=None):
    root = Path(data or os.environ.get("SIGNFACE_DATA", ".signface"))
    app = create_app(root / "preparation")
    install(app, root / "survey")
    return app


if __name__ == "__main__":
    serve(application(), host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")), threads=4)
