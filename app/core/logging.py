import logging
import re
import sys
from collections.abc import Mapping

import structlog

from app.core.config import get_settings

_SECRET_QUERY_RE = re.compile(
    r"(?i)([?&](?:token|api[_-]?key|apikey|api[_-]?secret|secret|password)=)[^&\s\"']+"
)
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_log_value(record.msg)
        if record.args:
            record.args = _redact_log_args(record.args)
        return True


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.app_log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )
    _install_secret_redaction_filter()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


def _install_secret_redaction_filter() -> None:
    root = logging.getLogger()
    if not any(isinstance(item, SecretRedactionFilter) for item in root.filters):
        root.addFilter(SecretRedactionFilter())
    for handler in root.handlers:
        if not any(isinstance(item, SecretRedactionFilter) for item in handler.filters):
            handler.addFilter(SecretRedactionFilter())


def _redact_log_args(args):
    if isinstance(args, Mapping):
        return {key: _redact_log_value(value) for key, value in args.items()}
    if isinstance(args, tuple):
        return tuple(_redact_log_value(value) for value in args)
    return _redact_log_value(args)


def _redact_log_value(value):
    if isinstance(value, str):
        return _redact_text(value)
    text = str(value)
    redacted = _redact_text(text)
    return redacted if redacted != text else value


def _redact_text(value: str) -> str:
    value = _SECRET_QUERY_RE.sub(r"\1<redacted>", value)
    return _BEARER_RE.sub(r"\1<redacted>", value)
