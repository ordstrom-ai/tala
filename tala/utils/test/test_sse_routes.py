import pytest

from tala.utils import sse_client, sse_routes


class TestSSEBrokerRoutes:
    @pytest.mark.parametrize(
        "route,host", [
            ("production", "production-sse-broker-ordstrom.azurewebsites.net"),
            ("staging", "staging-sse-broker-ordstrom.azurewebsites.net"),
        ]
    )
    def test_named_route_resolves_listener_and_publisher_endpoints(self, route, host):
        self.given_a_named_broker_route(route)
        self.when_broker_endpoints_are_resolved()
        self.then_both_transports_use_the_same_broker_host(host)

    def given_a_named_broker_route(self, route):
        self.route = route
        self.logger = object()

    def when_broker_endpoints_are_resolved(self):
        self.listener_endpoint = sse_routes.broker_listener_endpoint(self.route)
        self.publisher_origin = sse_routes.broker_publisher_origin(self.route)

    def then_both_transports_use_the_same_broker_host(self, host):
        assert self.listener_endpoint == f"https://{host}/event-sse"
        assert self.publisher_origin == f"wss://{host}"

    @pytest.mark.parametrize(
        "endpoint,expected_route", [
            ("https://production-sse-broker-ordstrom.azurewebsites.net/event-sse/", "production"),
            ("https://staging-sse-broker-ordstrom.azurewebsites.net/event-sse", "staging"),
            ("http://127.0.0.1:8000/event-sse", None),
            (None, None),
        ]
    )
    def test_listener_endpoint_selects_only_a_known_broker_route(self, endpoint, expected_route):
        self.given_a_listener_endpoint(endpoint)
        self.when_its_broker_route_is_resolved()
        self.then_only_a_known_endpoint_has_a_route(expected_route)

    def given_a_listener_endpoint(self, endpoint):
        self.endpoint = endpoint

    def when_its_broker_route_is_resolved(self):
        self.route = sse_routes.broker_route_for_listener_endpoint(self.endpoint)

    def then_only_a_known_endpoint_has_a_route(self, expected_route):
        assert self.route == expected_route

    def test_route_specific_sse_client_uses_its_selected_publisher_origin(self):
        self.given_a_named_broker_route("staging")
        self.when_a_route_specific_publisher_is_created()
        self.then_the_publisher_uses_the_staging_broker()

    def given_a_named_route_for_a_publisher(self, route):
        self.route = route
        self.logger = object()

    def when_a_route_specific_publisher_is_created(self):
        self.client = sse_client.SSEClient.for_broker_route("test-publisher", self.logger, self.route)

    def then_the_publisher_uses_the_staging_broker(self):
        assert self.client._endpoint == sse_routes.broker_publisher_origin("staging")

    @pytest.mark.parametrize("route", ["", "development", "https://example.invalid"])
    def test_unknown_route_is_rejected_instead_of_becoming_an_arbitrary_url(self, route):
        self.given_a_named_route_for_a_publisher(route)
        self.when_a_route_specific_publisher_is_created_with_error_capture()
        self.then_unknown_route_is_rejected()

    def when_a_route_specific_publisher_is_created_with_error_capture(self):
        self.error = None
        try:
            self.client = sse_client.SSEClient.for_broker_route("test-publisher", self.logger, self.route)
        except ValueError as error:
            self.error = error

    def then_unknown_route_is_rejected(self):
        assert self.error.args == ("Unknown SSE broker route",)

    @pytest.mark.parametrize("route", [None, "production", "staging"])
    def test_session_route_is_validated_and_legacy_sessions_remain_unrouted(self, route):
        self.given_a_session(route)
        self.when_its_route_is_read()
        self.then_the_route_is_preserved(route)

    def given_a_session(self, route):
        self.session = {} if route is None else {sse_routes.SSE_BROKER_ROUTE: route}

    def when_its_route_is_read(self):
        self.route = sse_routes.broker_route_from_session(self.session)

    def then_the_route_is_preserved(self, expected_route):
        assert self.route == expected_route
