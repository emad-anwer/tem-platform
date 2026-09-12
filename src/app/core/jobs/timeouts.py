import httpx

HTTP_CONNECT_TIMEOUT_SECONDS = 5.0
HTTP_READ_TIMEOUT_SECONDS = 15.0
HTTP_TOTAL_TIMEOUT_SECONDS = 30.0


def outbound_http_timeout() -> httpx.Timeout:
    """Return the standard timeout for one outbound HTTP request."""
    return httpx.Timeout(
        HTTP_TOTAL_TIMEOUT_SECONDS,
        connect=HTTP_CONNECT_TIMEOUT_SECONDS,
        read=HTTP_READ_TIMEOUT_SECONDS,
    )
