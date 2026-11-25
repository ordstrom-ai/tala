"""Broker destinations for routes assigned by the session owner, not the browser."""

from types import MappingProxyType


SSE_BROKER_ROUTE = "sse_broker_route"

_BROKER_HOSTS = MappingProxyType({
    "production": "production-sse-broker-ordstrom.azurewebsites.net",
    "staging": "staging-sse-broker-ordstrom.azurewebsites.net",
})


def broker_host(route: str) -> str:
    try:
        return _BROKER_HOSTS[route]
    except (KeyError, TypeError):
        raise ValueError("Unknown SSE broker route") from None


def broker_route_from_session(session):
    route = session.get(SSE_BROKER_ROUTE)
    if route is not None:
        broker_host(route)
    return route


def broker_route_for_listener_endpoint(endpoint: str | None):
    if endpoint is None:
        return None
    normalized_endpoint = endpoint.rstrip("/")
    for route in _BROKER_HOSTS:
        if normalized_endpoint == broker_listener_endpoint(route):
            return route
    return None


def broker_listener_endpoint(route: str) -> str:
    return f"https://{broker_host(route)}/event-sse"


def broker_publisher_origin(route: str) -> str:
    return f"wss://{broker_host(route)}"
