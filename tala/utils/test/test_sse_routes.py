import pytest

from tala.utils import sse_client
from tala.utils.sse_routes import publisher_origin_for_listener_endpoint


class TestSSEBrokerEndpoint:
    @pytest.mark.parametrize(
        "listener_endpoint,expected_publisher_origin", [
            ("https://example.invalid/event-sse", "wss://example.invalid"),
            ("https://example.invalid/event-sse/", "wss://example.invalid"),
            ("http://127.0.0.1:8123/event-sse", "ws://127.0.0.1:8123"),
            ("http://localhost:8123/event-sse/", "ws://localhost:8123"),
        ]
    )
    def test_listener_endpoint_resolves_a_safe_publisher_origin(
        self, listener_endpoint, expected_publisher_origin
    ):
        self.given_a_listener_endpoint(listener_endpoint)
        self.when_its_publisher_origin_is_resolved()
        self.then_the_expected_publisher_origin_is_used(expected_publisher_origin)

    def given_a_listener_endpoint(self, listener_endpoint):
        self.listener_endpoint = listener_endpoint

    def when_its_publisher_origin_is_resolved(self):
        self.publisher_origin = publisher_origin_for_listener_endpoint(self.listener_endpoint)

    def then_the_expected_publisher_origin_is_used(self, expected_publisher_origin):
        assert self.publisher_origin == expected_publisher_origin

    def test_route_specific_sse_client_uses_the_listener_endpoint_host(self):
        self.given_a_listener_endpoint("https://example.invalid/event-sse")
        self.when_a_route_specific_publisher_is_created()
        self.then_the_publisher_uses_the_resolved_origin()

    def when_a_route_specific_publisher_is_created(self):
        self.client = sse_client.SSEClient.for_broker_endpoint("test-publisher", object(), self.listener_endpoint)

    def then_the_publisher_uses_the_resolved_origin(self):
        assert self.client._endpoint == "wss://example.invalid"

    @pytest.mark.parametrize(
        "listener_endpoint", [
            "ftp://example.invalid/event-sse",
            "http://example.invalid/event-sse",
            "https://example.invalid/other",
            "https://user:password@example.invalid/event-sse",
            "https://example.invalid/event-sse?redirect=unsafe",
            "https://example.invalid/event-sse#fragment",
        ]
    )
    def test_invalid_listener_endpoint_is_rejected(self, listener_endpoint):
        self.given_a_listener_endpoint(listener_endpoint)
        self.when_its_publisher_origin_is_validated()
        self.then_the_listener_endpoint_is_rejected()

    def when_its_publisher_origin_is_validated(self):
        self.error = None
        try:
            publisher_origin_for_listener_endpoint(self.listener_endpoint)
        except ValueError as error:
            self.error = error

    def then_the_listener_endpoint_is_rejected(self):
        assert self.error.args == ("Invalid SSE listener endpoint",) or self.error.args == (
            "Non-local SSE listener endpoints must use HTTPS",
        )
