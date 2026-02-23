"""Users router — profile management."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

router = APIRouter()


@router.get("/me")
async def get_me() -> dict:
    # TODO: inject current user from JWT middleware
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented")


@router.get("/{user_id}")
async def get_user(user_id: UUID) -> dict:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented")
