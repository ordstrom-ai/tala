"""Convert a trusted SSE listener URL into the matching publisher origin."""

from urllib.parse import urlsplit, urlunsplit


def publisher_origin_for_listener_endpoint(listener_endpoint: str) -> str:
    try:
        parsed_endpoint = urlsplit(listener_endpoint)
        hostname = parsed_endpoint.hostname
    except ValueError as error:
        raise ValueError("Invalid SSE listener endpoint") from error

    if (
        parsed_endpoint.scheme not in {"https", "http"}
        or hostname is None
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
        or parsed_endpoint.query
        or parsed_endpoint.fragment
        or parsed_endpoint.path.rstrip("/") != "/event-sse"
    ):
        raise ValueError("Invalid SSE listener endpoint")
    if parsed_endpoint.scheme == "http" and hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Non-local SSE listener endpoints must use HTTPS")

    publisher_scheme = "wss" if parsed_endpoint.scheme == "https" else "ws"
    return urlunsplit((publisher_scheme, parsed_endpoint.netloc, "", "", ""))
