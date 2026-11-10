import json
from unittest.mock import Mock

import pytest

from tala.utils import sse_client
from tala.utils.mqtt_client import MQTTClient


@pytest.fixture
def client_and_websocket(monkeypatch):
    websocket = Mock()
    monkeypatch.setattr(sse_client.websocket, "WebSocket", lambda: websocket)
    client = sse_client.SSEClient("test", Mock(), "wss://example.invalid")
    client.sessions = {}
    try:
        yield client, websocket
    finally:
        for session in client.sessions.values():
            session["chunk_joiner"].last_chunk_sent()
            session["streamer_thread"].join(timeout=1)
        websocket.close()


def sent_messages(websocket):
    return [json.loads(call.args[0]) for call in websocket.send.call_args_list]


def expected_metadata(persona, voice):
    return [{
        "event": event,
        "data": value
    } for event, value in [(sse_client.STREAMING_SET_PERSONA, persona), (sse_client.STREAMING_SET_VOICE, voice)]
            if value]


class TestSSEMetadata:
    @pytest.mark.parametrize(
        "setter,event", [
            ("set_persona", sse_client.STREAMING_SET_PERSONA),
            ("set_voice", sse_client.STREAMING_SET_VOICE),
        ]
    )
    @pytest.mark.parametrize("value", [None, "", "specified", " "])
    def test_setters_send_only_nonempty_values(self, client_and_websocket, setter, event, value):
        client, websocket = client_and_websocket
        client.open_session("session")

        getattr(client, setter)("session", value)

        expected = [{"event": event, "data": value}] if value else []
        assert sent_messages(websocket) == expected
        assert client.sessions["session"]["message_counter"] == len(expected)

    @pytest.mark.parametrize("persona", [None, "", "persona"])
    @pytest.mark.parametrize("voice", [None, "", "voice"])
    def test_stream_utterance_skips_empty_metadata(self, client_and_websocket, persona, voice):
        client, websocket = client_and_websocket
        client.open_session("session")

        client.stream_utterance("session", persona, voice, "Hello")
        client.flush_stream("session")
        client.end_stream("session")

        assert sent_messages(websocket) == expected_metadata(persona, voice) + [
            {
                "event": sse_client.STREAMING_CHUNK,
                "data": "Hello "
            },
            {
                "event": sse_client.STREAMING_DONE
            },
        ]

    def test_omitted_metadata_does_not_emit_reset_events(self, client_and_websocket):
        client, websocket = client_and_websocket
        client.open_session("session")

        client.stream_utterance("session", utterance="Hello")
        client.flush_stream("session")
        client.end_stream("session")

        assert sent_messages(websocket) == [
            {
                "event": sse_client.STREAMING_CHUNK,
                "data": "Hello "
            },
            {
                "event": sse_client.STREAMING_DONE
            },
        ]

    @pytest.mark.parametrize("empty_value", [None, ""])
    def test_empty_metadata_does_not_reset_previous_settings(self, client_and_websocket, empty_value):
        client, websocket = client_and_websocket
        client.open_session("session")

        client.set_persona("session", "persona")
        client.set_voice("session", "voice")
        client.set_persona("session", empty_value)
        client.set_voice("session", empty_value)

        assert sent_messages(websocket) == expected_metadata("persona", "voice")

    @pytest.mark.parametrize("persona", [None, "", "persona"])
    @pytest.mark.parametrize("voice", [None, "", "voice"])
    def test_streamer_queue_skips_empty_metadata(self, client_and_websocket, persona, voice):
        client, websocket = client_and_websocket
        queue = sse_client.StreamerQueue(client, "session", "fallback", Mock())

        queue.setup_client({}, persona, voice)
        queue.enqueue("Hello ")
        queue.please_stop(end_stream=True)
        assert queue._setup_done.wait(timeout=1)
        queue.join(timeout=2)

        assert not queue.is_alive()
        assert not queue._setup_failed
        assert sent_messages(websocket) == expected_metadata(persona, voice) + [
            {
                "event": sse_client.STREAMING_CHUNK,
                "data": "Hello "
            },
            {
                "event": sse_client.STREAMING_DONE
            },
        ]


class TestMQTTMetadataCompatibility:
    @pytest.mark.parametrize(
        "setter,event", [
            ("set_persona", sse_client.STREAMING_SET_PERSONA),
            ("set_voice", sse_client.STREAMING_SET_VOICE),
        ]
    )
    @pytest.mark.parametrize("value", [None, ""])
    def test_mqtt_empty_metadata_behavior_is_unchanged(self, setter, event, value):
        client = MQTTClient("test", Mock(), "example.invalid")
        client.sessions = {"session": {"session_id": "session"}}
        client._stream_to_frontend = Mock()

        getattr(client, setter)("session", value)

        client._stream_to_frontend.assert_called_once_with(client.sessions["session"], {"event": event, "data": ""})
