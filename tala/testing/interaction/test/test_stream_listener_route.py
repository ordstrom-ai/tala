from unittest.mock import Mock

from tala.testing.interaction import interaction_tester


class TestInteractionTesterStreamRoute:
    def test_session_endpoint_selects_the_sse_listener_target(self, monkeypatch):
        self.given_an_interaction_tester_with_a_session_route(monkeypatch)
        self.when_the_sse_listener_starts()
        self.then_the_listener_uses_the_session_endpoint()

    def test_legacy_session_uses_the_configured_listener_fallback(self, monkeypatch):
        self.given_an_interaction_tester_without_a_session_route(monkeypatch)
        self.when_the_sse_listener_starts()
        self.then_the_listener_uses_the_configured_fallback()

    def given_an_interaction_tester_with_a_session_route(self, monkeypatch):
        self.session_endpoint = "https://production.example/event-sse/"
        self.given_an_interaction_tester(monkeypatch, {"sse_endpoint": self.session_endpoint})

    def given_an_interaction_tester_without_a_session_route(self, monkeypatch):
        self.given_an_interaction_tester(monkeypatch, {})

    def given_an_interaction_tester(self, monkeypatch, session):
        self.listener_factory = Mock()
        self.listener_factory.SSE_BROKER_ENDPOINT_HTTPS = "https://legacy.example/event-sse"
        monkeypatch.setattr(interaction_tester, "StreamListener", self.listener_factory)
        self.tester = object.__new__(interaction_tester.InteractionTester)
        self.tester._use_streaming = True
        self.tester._session_data = session
        self.tester._session_id = "synthetic-session"

    def when_the_sse_listener_starts(self):
        self.tester._start_stream_listener()

    def then_the_listener_uses_the_session_endpoint(self):
        self.listener_factory.assert_called_once_with(
            self.session_endpoint.rstrip("/"), "synthetic-session", interaction_tester.logger
        )
        listener = self.listener_factory.return_value
        listener.start.assert_called_once_with()
        listener.wait_until_started.assert_called_once_with()

    def then_the_listener_uses_the_configured_fallback(self):
        self.listener_factory.assert_called_once_with(
            "https://legacy.example/event-sse", "synthetic-session", interaction_tester.logger
        )
