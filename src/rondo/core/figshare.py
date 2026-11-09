"""Download figshare articles once, verified against figshare's MD5, with a SOURCE.json."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from rondo import __version__

USER_AGENT = f"RondoBot/{__version__} (https://github.com/Moulik04) python-urllib"


def get(url: str) -> bytes:
    """GET a URL with Rondo's User-Agent."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


def download(url: str, path: Path) -> None:
    """Stream a URL to a file (large files never sit in memory)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = path.with_suffix(path.suffix + ".part")
    with urllib.request.urlopen(req, timeout=600) as r, tmp.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.rename(path)


def digest(path: Path, algo: str) -> str:
    """Hex digest of a file, streamed."""
    h = hashlib.new(algo)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_articles(
    root: Path, provider: str, articles: dict[str, int], extra: dict[str, Any] | None = None
) -> Path:
    """Download (or verify) every file of every article, unzip archives, write SOURCE.json."""
    root.mkdir(parents=True, exist_ok=True)
    meta_out: dict[str, Any] = {}
    files: dict[str, Any] = {}
    for key, article_id in articles.items():
        meta = json.loads(get(f"https://api.figshare.com/v2/articles/{article_id}"))
        meta_out[key] = {
            "id": article_id,
            "doi": meta["doi"],
            "title": meta["title"],
            "license": meta["license"]["name"],
        }
        for f in meta["files"]:
            path = root / f["name"]
            if not (path.exists() and digest(path, "md5") == f["computed_md5"]):
                print(f"downloading {f['name']} ({f['size'] / 1e6:.1f} MB)", flush=True)
                download(f["download_url"], path)
            if digest(path, "md5") != f["computed_md5"]:
                raise RuntimeError(f"{f['name']}: MD5 does not match figshare's")
            files[f["name"]] = {
                "article": key,
                "bytes": path.stat().st_size,
                "md5": f["computed_md5"],
                "sha256": digest(path, "sha256"),
            }
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as z:
                    z.extractall(root)
                    for name in z.namelist():
                        member = root / name
                        if member.is_file():
                            files[name] = {
                                "from_zip": f["name"],
                                "bytes": member.stat().st_size,
                                "sha256": digest(member, "sha256"),
                            }
    source = {
        "provider": provider,
        **(extra or {}),
        "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "articles": meta_out,
        "files": files,
    }
    out = root / "SOURCE.json"
    out.write_text(json.dumps(source, indent=1))
    print(f"wrote {out} ({len(files)} files)")
    return out


def fetched(root: Path) -> bool:
    """Return True if every file in SOURCE.json is present with its recorded SHA-256."""
    src = root / "SOURCE.json"
    if not src.exists():
        return False
    meta = json.loads(src.read_text())
    return all(
        (root / name).exists() and digest(root / name, "sha256") == f["sha256"]
        for name, f in meta["files"].items()
    )
