"""Response envelope utilities for consistent API response formatting."""

from math import ceil


def success_response(data: object, request_id: str) -> dict:
    """Wrap a single resource response in the standard envelope."""
    return {"data": data, "meta": {"request_id": request_id}}


def list_response(data: list, total: int, page: int, page_size: int, request_id: str) -> dict:
    """Wrap a paginated list response in the standard envelope."""
    return {
        "data": data,
        "meta": {
            "request_id": request_id,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": ceil(total / page_size) if page_size > 0 else 0,
        },
    }
