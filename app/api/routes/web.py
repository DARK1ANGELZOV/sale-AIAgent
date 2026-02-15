"""Web UI route."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["web"])
BASE_DIR = Path(__file__).resolve().parents[2]
WEB_DIR = BASE_DIR / "web"


@router.get("/", include_in_schema=False)
async def index_page() -> FileResponse:
    """Serve single-page web UI."""
    return FileResponse(WEB_DIR / "index.html")
