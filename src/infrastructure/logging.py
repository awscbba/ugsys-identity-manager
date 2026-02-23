"""Enterprise structured logging configuration."""

import logging

import structlog


def configure_logging(service_name: str, log_level: str = "INFO") -> None:
    """Configure structlog for JSON output with CloudWatch-ready format."""
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

    structlog.get_logger().bind(service=service_name)
