"""The browser extension as a zip, for the download on the website's /extension page.

Built from extension/ at the repo root on each request, so the download always matches the code.
The files go in one top-level folder, which is what Chrome's "Load unpacked" asks for. The route
that serves it (GET /api/extension.zip in main.py) is for signed-in accounts only during the beta.
"""

import io
import zipfile

from app.config import REPO_ROOT

EXTENSION_DIR = REPO_ROOT / "extension"
FOLDER = "dossier-privacy-check"
FILENAME = f"{FOLDER}.zip"


def zip_extension() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(EXTENSION_DIR.rglob("*")):
            relative = path.relative_to(EXTENSION_DIR)
            # Plain files only: no hidden files, and no links that could point outside the folder.
            if path.is_file() and not path.is_symlink() and not any(part.startswith(".") for part in relative.parts):
                archive.write(path, f"{FOLDER}/{relative.as_posix()}")
    return buffer.getvalue()
