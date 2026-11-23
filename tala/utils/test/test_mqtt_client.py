import json
from unittest.mock import Mock
import uuid

import pytest
import structlog

from tala.utils.mqtt_client import MQTTClient
from tala.utils.func import configure_stdout_logging, getenv

logger = structlog.get_logger(__name__)
log_level = getenv("LOG_LEVEL", default="DEBUG")
configure_stdout_logging(log_level)


class TestMQTTClient:
    @pytest.fixture(autouse=True)
    def mocked_transport(self, monkeypatch):
        self._transport = Mock()
        monkeypatch.setattr("tala.utils.mqtt_client.mqtt.Client", Mock(return_value=self._transport))

        def connected():
            self._transport.on_connect(self._transport, None, {}, 0, None)

        self._transport.loop_start.side_effect = connected

    def test_creation(self):
        self.given_args_for_client_creation(["", logger, "some_endpoint", 443])
        self.when_mqtt_client_created()
        self.then_client_created_with(logger, "some_endpoint", 443, "name_base")

    def test_client_summary_identifies_mqtt_transport(self):
        self.given_args_for_client_creation(["", logger, "some_endpoint", 443])
        self.when_mqtt_client_created()
        self.then_transport_is_identified_as_mqtt()

    def given_args_for_client_creation(self, args):
        self._mqtt_args = args

    def when_mqtt_client_created(self):
        self._mqtt_client = MQTTClient(*self._mqtt_args)

    def then_client_created_with(self, logger, endpoint, port, name_base):
        assert self._mqtt_client.logger == logger
        assert self._mqtt_client._endpoint == endpoint
        assert self._mqtt_client._port == port

    def then_transport_is_identified_as_mqtt(self):
        assert self._mqtt_client.transport == "mqtt"

    def test_creation_with_client_id(self):
        self.given_args_for_client_creation(["client_id", logger, "some_endpoint", 443])
        self.when_mqtt_client_created()
        self.then_client_id_matches("client_id")

    def then_client_id_matches(self, id_):
        assert self._mqtt_client._client_id.startswith(f"{id_}-")

    @pytest.mark.parametrize("chunk", ["This is an unproblematic test utterance.", "Frölunda ", "Fr\u00f6lunda"])
    def test_stream_single_chunk(self, chunk):
        self.given_streamer_endpoint()
        self.given_mqtt_client_started("test_client", logger, self._endpoint, 443)
        self.given_session_id("test-session-id")
        self.when_chunk_streamed(chunk)
        self.then_messages_published(chunk)

    def test_response_send_observation_precedes_mqtt_publish(self, monkeypatch):
        self.given_response_mqtt_stream(monkeypatch)
        self.when_response_chunk_is_published()
        self.then_response_send_is_observed_before_publish()

    def given_response_mqtt_stream(self, monkeypatch):
        self._timeline = []
        self._client = MQTTClient("test-client", logger, "broker.example.test", 443)
        self._client._connected.set()
        self._session_id = "response-session"
        self._client.open_session(self._session_id, logger=logger.bind(stream_content_role="response"))
        self._streamer_session = self._client.sessions[self._session_id]
        monkeypatch.setattr(
            self._client,
            "_start_first_response_content_send",
            lambda *_args: self._timeline.append("response-send-observation") or True,
        )
        self._transport.publish.side_effect = lambda *_args: self._timeline.append("mqtt-publish")

    def when_response_chunk_is_published(self):
        try:
            self._client._stream_to_frontend(
                self._streamer_session,
                {
                    "event": "STREAMING_CHUNK",
                    "data": "response"
                },
            )
        finally:
            self._streamer_session["chunk_joiner"].last_chunk_sent()
            self._streamer_session["streamer_thread"].join(timeout=1)

    def then_response_send_is_observed_before_publish(self):
        assert self._timeline == ["response-send-observation", "mqtt-publish"]

    def given_mqtt_client_started(self, name, logger, endpoint, port):
        self._client = MQTTClient(name, logger, endpoint, port)
        self._client.start()

    def given_session_id(self, id_):
        self._session_id = id_ + str(uuid.uuid4())

    def when_chunk_streamed(self, chunk):
        self._client.open_session(self._session_id, None)
        self._client.set_persona(self._session_id, "some-persona")
        self._client.set_voice(self._session_id, "some-voice")
        self._client.stream_chunk(self._session_id, chunk)
        self._client.flush_stream(self._session_id)
        self._client.close_session(self._session_id)

    def then_messages_published(self, chunk):
        self._transport.tls_set.assert_called_once_with()
        self._transport.connect.assert_called_once_with(self._endpoint, 443)
        self._transport.loop_start.assert_called_once_with()
        messages = [
            (call.args[0], json.loads(call.args[1])) for call in self._transport.publish.call_args_list
        ]
        topic = f"tm/id/{self._session_id}"
        assert messages == [
            (topic, {"event": "STREAMING_SET_PERSONA", "data": "some-persona"}),
            (topic, {"event": "STREAMING_SET_VOICE", "data": "some-voice"}),
            (topic, {"event": "STREAMING_CHUNK", "data": chunk}),
        ]
        assert self._session_id not in self._client.sessions

    def given_streamer_endpoint(self):
        self._endpoint = "broker.example.test"
