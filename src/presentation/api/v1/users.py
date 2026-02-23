"""Users router — /api/v1/users endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
async def get_me() -> dict:  # type: ignore[type-arg]
    # TODO: inject current user from JWT middleware
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented")


@router.get("/{user_id}")
async def get_user(user_id: UUID) -> dict:  # type: ignore[type-arg]
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented")
