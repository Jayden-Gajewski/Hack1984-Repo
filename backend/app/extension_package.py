"""The browser extension as a zip, for the download on the website's /extension page.

Built from extension/ at the repo root on each request, so the download always matches the code.
The files go in one top-level folder, which is what Chrome's "Load unpacked" asks for. The route
that serves it (GET /api/extension.zip in main.py) is for signed-in accounts only during the beta.

The extension in the repo checks sites with Dossier on this computer (extension/config.js). People
who download it from the public site don't have the repo or a backend of their own, so that copy
gets a config.js pointing at the public site (they use it signed in to their account there), and a
manifest whose only host permission is that site.
"""

import io
import json
import zipfile

from app.config import REPO_ROOT

EXTENSION_DIR = REPO_ROOT / "extension"
FOLDER = "dossier-privacy-check"
FILENAME = f"{FOLDER}.zip"


def hosted_config(site_url: str) -> str:
    """extension/config.js for the copy downloaded from the public site (site_url is SITE_URL,
    already checked by config.py to be an https address)."""
    site = json.dumps(site_url.rstrip("/"))
    return (
        "// Written by Dossier's public site for this download (backend/app/extension_package.py).\n"
        "// This copy checks sites with the public site, signed in to your own account there.\n"
        "export const HOSTED = true;\n"
        f"export const BACKEND = {site};\n"
        f"export const APP_ORIGIN = {site};\n"
    )


def hosted_manifest(manifest: str, site_url: str) -> str:
    """manifest.json for that copy: the public site is the only address it may call."""
    data = json.loads(manifest)
    data["host_permissions"] = [f"{site_url.rstrip('/')}/*"]
    data["description"] = (
        "See what each site's privacy policy says it collects and shares. Checked by Dossier with your account."
    )
    return json.dumps(data, indent=2) + "\n"


def zip_extension(site_url: str = "") -> bytes:
    """The extension's folder as a zip. With site_url (the public site), set up for that site."""
    if not (EXTENSION_DIR / "manifest.json").is_file():
        # A host that deploys only backend/ (render.yaml must not set rootDir) would serve an empty zip.
        raise FileNotFoundError(f"The extension isn't deployed next to the backend: {EXTENSION_DIR} is missing.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(EXTENSION_DIR.rglob("*")):
            relative = path.relative_to(EXTENSION_DIR)
            # Plain files only: no hidden files, and no links that could point outside the folder.
            if not path.is_file() or path.is_symlink() or any(part.startswith(".") for part in relative.parts):
                continue
            name = f"{FOLDER}/{relative.as_posix()}"
            if site_url and relative.as_posix() == "config.js":
                archive.writestr(name, hosted_config(site_url))
            elif site_url and relative.as_posix() == "manifest.json":
                archive.writestr(name, hosted_manifest(path.read_text(encoding="utf-8"), site_url))
            else:
                archive.write(path, name)
    return buffer.getvalue()
