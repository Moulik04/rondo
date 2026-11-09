"""A polite, cached Wikidata client (identity and birth dates only; see docs/DATA_TERMS.md).

Etiquette, from the Wikidata Query Service user manual and the Wikimedia User-Agent policy:

- a descriptive User-Agent naming the project and https://github.com/Moulik04 (no email);
- one request at a time, with a pause between requests;
- every response cached on disk (``data/raw/wikidata/cache/``) and never re-fetched;
- on HTTP 429 or 5xx, wait for ``Retry-After`` (or back off exponentially), and give up after
  repeated errors; Action API calls send ``maxlag=5``.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from rondo import __version__
from rondo.core.paths import data_dir

USER_AGENT = f"RondoBot/{__version__} (https://github.com/Moulik04) python-urllib"
SPARQL_URL = "https://query.wikidata.org/sparql"
API_URL = "https://www.wikidata.org/w/api.php"
PAUSE_S = 1.0
MAX_TRIES = 6


def cache_dir() -> Path:
    """Return the on-disk response cache."""
    return data_dir() / "raw" / "wikidata" / "cache"


class Client:
    """Serial, cached requests to the Wikidata Query Service and Action API."""

    def __init__(self, cache: Path | None = None, offline: bool = False) -> None:
        """Use ``cache`` (default ``data/raw/wikidata/cache``); ``offline`` forbids fetching."""
        self.cache = cache or cache_dir()
        self.cache.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.fetched = 0
        self.cached = 0
        self._last = 0.0

    def _path(self, kind: str, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()[:32]
        return self.cache / kind / digest[:2] / f"{digest}.json"

    def _get(self, url: str, data: bytes | None = None) -> Any:
        for attempt in range(MAX_TRIES):
            wait = PAUSE_S - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    **({"Content-Type": "application/x-www-form-urlencoded"} if data else {}),
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    self._last = time.monotonic()
                    return json.loads(r.read())
            except urllib.error.HTTPError as err:
                self._last = time.monotonic()
                if err.code in (429, 500, 502, 503, 504):
                    retry = err.headers.get("Retry-After")
                    delay = float(retry) if retry and retry.isdigit() else 2 ** (attempt + 1)
                    print(f"wikidata: HTTP {err.code}, waiting {delay:.0f}s", flush=True)
                    time.sleep(delay)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError) as err:
                self._last = time.monotonic()
                delay = 2 ** (attempt + 1)
                print(f"wikidata: {err}, waiting {delay}s", flush=True)
                time.sleep(delay)
        raise RuntimeError(f"wikidata: giving up after {MAX_TRIES} tries: {url[:120]}")

    def _cached(self, kind: str, key: str, fetch: Any) -> Any:
        path = self._path(kind, key)
        if path.exists():
            self.cached += 1
            return json.loads(path.read_text())
        if self.offline:
            raise RuntimeError(f"wikidata: offline and not cached ({kind})")
        result = fetch()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result))
        self.fetched += 1
        return result

    def sparql(self, query: str) -> list[dict[str, str]]:
        """Run a SPARQL query; return bindings as {variable: value} dicts."""

        def fetch() -> Any:
            body = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
            return self._get(SPARQL_URL, data=body)

        res = self._cached("sparql", query, fetch)
        return [{k: v["value"] for k, v in b.items()} for b in res["results"]["bindings"]]

    def api(self, **params: str) -> Any:
        """Call the Action API (GET), with ``format=json`` and ``maxlag=5``."""
        params = {**params, "format": "json", "maxlag": "5"}
        key = json.dumps(params, sort_keys=True)

        def fetch() -> Any:
            res = self._get(f"{API_URL}?{urllib.parse.urlencode(params)}")
            if "error" in res:
                raise RuntimeError(f"wikidata API error: {res['error']}")
            return res

        return self._cached("api", key, fetch)

    def search(self, text: str, language: str = "en", limit: int = 7) -> list[dict[str, Any]]:
        """Entity search (``wbsearchentities``); returns candidate items."""
        res = self.api(
            action="wbsearchentities",
            search=text,
            language=language,
            uselang=language,
            type="item",
            limit=str(limit),
        )
        return res.get("search", [])
