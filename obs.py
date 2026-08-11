"""Structured JSON logging for the Askable pipeline.

Every log line is a newline-delimited JSON object — easy to grep, parse, and
ship to any observability platform (Datadog, Splunk, CloudWatch).

Usage:
    from obs import configure_json_logging, emit

    configure_json_logging()   # call once at startup

    emit(log, "pipeline_end", query_id="abc123", context_len=1200, total_ms=312.4)
"""

import json
import logging
import time


class JsonFormatter(logging.Formatter):
    """Format every log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        # Merge in any extra structured fields added via emit()
        extra = getattr(record, "json_fields", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload)


def configure_json_logging(level: str = "INFO") -> None:
    """Replace the root logger's handlers with a JsonFormatter handler."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def emit(logger: logging.Logger, event: str, **fields) -> None:
    """Log a structured event with arbitrary keyword fields.

    Example:
        emit(log, "pipeline_end", query_id="abc", context_len=1200, cache_hit=False)
    """
    logger.info(event, extra={"json_fields": fields})
