"""The Rondo API. Track routers (value_*.py, scout_*.py) are mounted here as they land."""

from fastapi import FastAPI

from rondo import SITE_TITLE, __version__

app = FastAPI(title=SITE_TITLE, version=__version__)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Report that the API is up and which version is running."""
    return {"status": "ok", "version": __version__}
