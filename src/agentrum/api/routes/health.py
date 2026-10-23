from fastapi import APIRouter

from agentrum import __version__

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "name": "agentrum", "version": __version__}
