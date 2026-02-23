"""Health check router."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:  # type: ignore[type-arg]
    return {"status": "ok", "service": "ugsys-identity-manager"}
