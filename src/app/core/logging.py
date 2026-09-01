import logging

import structlog

SENSITIVE_KEYS = {
    "password", "passwd", "pwd",
    "token", "access_token", "refresh_token", "id_token",
    "authorization", "auth",
    "api_key", "apikey", "x-api-key",
    "secret", "client_secret",
    "jwt", "masterkey", "master_key",
    "credentials", "private_key",
    "cookie", "set-cookie",
}

REDACTED = "***REDACTED***"

def redact_processor(logger, method_name, event_dict):
    def redact(data):
        if isinstance(data, dict):
            return {
                k: (REDACTED if k.lower() in SENSITIVE_KEYS else redact(v))
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [redact(item) for item in data]
        return data
    return redact(event_dict)

def setup_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(message)s")

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,   
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_processor,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
