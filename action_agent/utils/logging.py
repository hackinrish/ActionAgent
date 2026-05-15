import json
import logging
from datetime import datetime, timezone

_JSON_FMT = logging.Formatter("%(message)s")
_EXTRA_KEYS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
})


class _JsonLogger(logging.Logger):
    """Logger whose records are emitted as JSON lines."""

    def callHandlers(self, record: logging.LogRecord) -> None:
        extra: dict = {
            k: v for k, v in record.__dict__.items()
            if k not in _EXTRA_KEYS and not k.startswith("_")
        }
        json_msg = json.dumps({
            "level": record.levelname,
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "message": record.getMessage(),
            "logger": record.name,
            **extra,
        })
        record.msg = json_msg
        record.args = ()

        # Handlers added without a formatter would use the default %(levelname)s:%(name)s:%(message)s
        # format which wraps our JSON. Temporarily inject %(message)s-only formatter so they emit
        # the JSON string as-is.
        injected: list[logging.Handler] = []
        for h in self.handlers:
            if h.formatter is None:
                h.setFormatter(_JSON_FMT)
                injected.append(h)
        try:
            super().callHandlers(record)
        finally:
            for h in injected:
                h.setFormatter(None)


def get_logger(name: str) -> logging.Logger:
    """Return a structured JSON logger. Identical names return the same instance."""
    prev_class = logging.getLoggerClass()
    logging.setLoggerClass(_JsonLogger)
    logger = logging.getLogger(name)
    logging.setLoggerClass(prev_class)

    if not logger.handlers:
        handler = logging.StreamHandler()
        logger.addHandler(handler)
    if not logger.level:
        logger.setLevel(logging.INFO)
    return logger


def log_node_event(logger: logging.Logger, *, node_name: str, event: str) -> None:
    """Emit a structured log line tagged with the LangGraph node name."""
    logger.info(event, extra={"node": node_name})
