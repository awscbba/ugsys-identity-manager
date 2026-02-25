"""List users query (read DTO) with pagination and filtering."""

from dataclasses import dataclass


@dataclass
class ListUsersQuery:
    """Query to list users with pagination and optional filters."""

    page: int = 1
    page_size: int = 20
    status_filter: str | None = None
    role_filter: str | None = None
    admin_id: str = ""
