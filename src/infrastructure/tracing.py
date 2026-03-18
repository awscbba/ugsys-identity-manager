"""AWS X-Ray tracing configuration.

Patches boto3 and requests so all outbound calls are automatically traced.
Only active when XRAY_ENABLED=true — safe to leave off in local dev.
"""

import structlog
from aws_xray_sdk.core import patch, xray_recorder
from aws_xray_sdk.core.context import Context

logger = structlog.get_logger()

# Libraries to auto-patch — adds X-Ray subsegments for every outbound call
# Note: "requests" is intentionally excluded — this service uses httpx, not requests.
# Patching a module that isn't installed causes a startup crash.
_PATCH_MODULES = ("boto3", "httpx")


def configure_tracing(service_name: str) -> None:
    """Initialise X-Ray recorder and patch outbound libraries."""
    xray_recorder.configure(
        service=service_name,
        context_missing="LOG_ERROR",  # don't crash if no segment exists (e.g. local dev)
        plugins=("EC2Plugin",),
        context=Context(),
    )
    patch(_PATCH_MODULES)
    logger.info("tracing.configured", service=service_name, patches=list(_PATCH_MODULES))
