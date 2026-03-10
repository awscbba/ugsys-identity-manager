"""JWKS endpoint — exposes the public key set for RS256 token verification.

GET /.well-known/jwks.json

This endpoint is public (no auth required). Other services and the admin panel
fetch it to obtain the RSA public key needed to verify JWTs issued by this service.

RFC 7517 — JSON Web Key Set
RFC 7518 §6.3 — RSA key parameters (n, e)
"""

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.config import settings
from src.infrastructure.adapters.jwt_token_service import JWTTokenService

logger = structlog.get_logger()
router = APIRouter(tags=["jwks"])


@router.get(
    "/.well-known/jwks.json",
    summary="JSON Web Key Set",
    description="Public key set for RS256 JWT verification. No authentication required.",
    include_in_schema=True,
)
async def jwks() -> JSONResponse:
    """Return the JWKS document containing the active RSA public key."""
    svc = JWTTokenService(
        private_key=settings.jwt_private_key,
        public_key=settings.jwt_public_key,
        key_id=settings.jwt_key_id,
    )
    jwks_doc = svc.get_jwks()
    logger.debug("jwks.served", key_id=settings.jwt_key_id)
    return JSONResponse(
        content=jwks_doc,
        headers={
            # Cache for 1 hour — consumers should re-fetch when kid is unknown
            "Cache-Control": "public, max-age=3600",
        },
    )
