"""Get user query (read DTO)."""

from dataclasses import dataclass
from uuid import UUID


@dataclass
class GetUserQuery:
    user_id: UUID
    requester_id: str  # from JWT sub — used for IDOR check
    is_admin: bool = False
