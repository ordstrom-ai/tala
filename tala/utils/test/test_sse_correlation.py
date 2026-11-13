import json
from unittest.mock import Mock
from threading import Event, Thread

import structlog
import pytest

from tala.utils import sse_client


class TestSSEStreamCorrelation:
    @pytest.mark.parametrize("enabled,expected_chunks", [(True, ["Howdy "]), (False, ["Hel", "lo "])])
    def test_pronunciation_modes_preserve_stream_handle_and_context(self, monkeypatch, enabled, expected_chunks):
        self.given_fake_websockets_and_client(monkeypatch)
        self.given_pronunciation_mode(monkeypatch, enabled)
        try:
            self.when_pronunciation_chunks_are_sent()
            self.then_pronunciation_text_and_context_match(expected_chunks)
        finally:
            self.cleanup_streams()

    @pytest.mark.parametrize(
        "call_style,expected_chunks", [
            ("positional_mode", ["Hel", "lo "]),
            ("keyword_mode", ["Hello "]),
            ("positional_record", ["Hello "]),
        ]
    )
    def test_streamer_helper_preserves_both_parent_call_styles(self, monkeypatch, call_style, expected_chunks):
        self.given_fake_websockets_and_client(monkeypatch)
        self.given_helper_call_style(call_style)
        self.when_helper_chunks_are_collected()
        self.then_helper_chunks_match(expected_chunks)

    def given_pronunciation_mode(self, monkeypatch, enabled):
        self.pronunciation_enabled = enabled
        monkeypatch.setenv("PRONUNCIATION_REPLACEMENTS_ENABLED", "true" if enabled else "false")
        self.pronunciation_stream = self.client.open_session(
            "conversation", {"Hello": "Howdy"}, logger=self.request_logger("request-1")
        )

    def when_pronunciation_chunks_are_sent(self):
        self.client.stream_chunk(self.pronunciation_stream, "Hel")
        self.client.stream_chunk(self.pronunciation_stream, "lo ")
        self.client.flush_stream(self.pronunciation_stream)
        self.client.end_stream(self.pronunciation_stream)

    def then_pronunciation_text_and_context_match(self, expected_chunks):
        messages = self.websockets[0].messages
        assert [message["data"] for message in messages[:-1]] == expected_chunks
        assert messages[-1]["event"] == "STREAMING_DONE"
        assert all(message["stream_id"] == self.pronunciation_stream.stream_id for message in messages)
        assert all(message["correlation"]["request_id"] == "request-1" for message in messages)
        expected_model = {"Hello": "Howdy"} if self.pronunciation_enabled else {}
        assert self.pronunciation_stream.streamer_session["search_and_replace_dict"] == expected_model

    def given_helper_call_style(self, call_style):
        prepare = sse_client.AbstractSSEClient._prepare_streamer_thread
        if call_style == "positional_mode":
            self.helper_thread, self.helper_joiner = prepare(self.client, "conversation", False)
        elif call_style == "keyword_mode":
            self.helper_thread, self.helper_joiner = prepare(
                self.client, "conversation", apply_pronunciation_replacements=True
            )
        else:
            record = {"session_id": "conversation", "search_and_replace_dict": {"Hello": "Howdy"}, "logger": Mock()}
            self.helper_thread, self.helper_joiner = prepare(self.client, "conversation", record)

    def when_helper_chunks_are_collected(self):
        self.helper_joiner.add_chunk("Hel")
        self.helper_joiner.add_chunk("lo ")
        self.helper_joiner.last_chunk_sent()
        self.helper_chunks = list(self.helper_joiner)

    def then_helper_chunks_match(self, expected_chunks):
        assert self.helper_chunks == expected_chunks
        assert self.helper_thread.daemon
        assert self.helper_thread.ident is None

    def test_overlapping_failed_opens_leave_the_original_active_session(self, monkeypatch):
        self.given_fake_websockets_and_client(monkeypatch)
        self.given_an_active_stream()
        self.given_two_blocked_connections(monkeypatch, fail=True)
        readers = [
            Thread(target=self.open_blocked_stream, args=(request_id, )) for request_id in ("request-2", "request-3")
        ]
        try:
            readers[0].start()
            assert self.connection_entered[0].wait(1)
            readers[1].start()
            assert self.connection_entered[1].wait(1)
            self.connection_release[0].set()
            readers[0].join(1)
            self.connection_release[1].set()
            readers[1].join(1)
            assert all(not reader.is_alive() for reader in readers)
            assert len(self.open_errors) == 2
            assert self.client.sessions["conversation"] is self.first.streamer_session
            self.then_stream_still_delivers(self.first, self.websockets[0])
        finally:
            self.release_connections_and_cleanup(readers)

    def test_older_successful_open_does_not_replace_a_newer_connected_stream(self, monkeypatch):
        self.given_fake_websockets_and_client(monkeypatch)
        self.given_an_active_stream()
        self.given_two_blocked_connections(monkeypatch, fail=False)
        older = Thread(target=self.open_blocked_stream, args=("request-2", ))
        try:
            older.start()
            assert self.connection_entered[0].wait(1)
            self.connection_release[1].set()
            newer = self.client.open_session("conversation", logger=self.request_logger("request-3"))
            self.connection_release[0].set()
            older.join(1)
            assert not older.is_alive()
            assert self.open_errors == []
            assert self.client.sessions["conversation"] is newer.streamer_session
            self.then_stream_still_delivers(self.opened_streams[0], self.websockets[1])
            self.then_stream_still_delivers(newer, self.websockets[2])
        finally:
            self.release_connections_and_cleanup([older])

    def test_joiner_start_failure_keeps_the_original_session_and_closes_the_socket(self, monkeypatch):
        self.given_fake_websockets_and_client(monkeypatch)
        self.given_an_active_stream()
        try:
            with monkeypatch.context() as patcher:
                patcher.setattr(
                    sse_client.threading.Thread, "start", Mock(side_effect=RuntimeError("thread unavailable"))
                )
                with pytest.raises(RuntimeError, match="thread unavailable"):
                    self.client.open_session("conversation", logger=self.request_logger("request-2"))
            assert self.client.sessions["conversation"] is self.first.streamer_session
            assert self.websockets[-1].closed
            self.then_stream_still_delivers(self.first, self.websockets[0])
        finally:
            self.cleanup_streams()

    def test_failed_send_raises_the_stream_error_without_using_another_streams_output(self, monkeypatch):
        self.given_fake_websockets_and_client(monkeypatch)
        self.given_an_active_stream()
        self.websockets[0].send = Mock(side_effect=[None, RuntimeError("synthetic send failure")])
        try:
            self.client.stream_chunk(self.first, "before failure ")
            self.client.stream_chunk(self.first, "failed output ")
            self.client.flush_stream(self.first)
            newer = self.client.open_session("conversation", logger=self.request_logger("request-2"))
            self.then_stream_still_delivers(newer, self.websockets[1])
            with pytest.raises(sse_client.SSEClientException, match="synthetic send failure") as raised:
                self.client.close_session(self.first)
            assert raised.value.__cause__ is self.first.streamer_session["streaming_exception"]
            assert "before failure" in str(raised.value)
            assert "still healthy" not in str(raised.value)
        finally:
            self.cleanup_streams()

    @pytest.mark.parametrize("close_fails", [False, True])
    def test_failed_open_stops_its_thread_and_does_not_replace_an_active_stream(self, monkeypatch, close_fails):
        self.given_fake_websockets_and_client(monkeypatch)
        self.given_an_active_stream()
        self.given_connection_failure(monkeypatch, close_fails=close_fails)
        try:
            self.when_open_fails()
            self.then_failed_stream_is_stopped()
            assert self.client.sessions["conversation"] is self.first.streamer_session
            self.then_stream_still_delivers(self.first, self.websockets[0])
        finally:
            self.cleanup_streams()

    @pytest.mark.parametrize("failure_point", ["connect", "construct"])
    def test_failed_first_open_removes_the_unusable_session(self, monkeypatch, failure_point):
        self.given_fake_websockets_and_client(monkeypatch)
        self.given_connection_failure(monkeypatch, failure_point=failure_point)
        try:
            self.when_open_fails()
            self.then_failed_stream_is_stopped()
            assert "conversation" not in self.client.sessions
        finally:
            self.cleanup_streams()

    def test_failed_open_does_not_restore_over_a_newer_successful_stream(self, monkeypatch):
        self.given_fake_websockets_and_client(monkeypatch)
        self.given_an_active_stream()
        self.given_connection_failure(monkeypatch, open_newer_stream=True)
        try:
            self.when_open_fails()
            self.then_failed_stream_is_stopped()
            assert self.client.sessions["conversation"] is self.newer.streamer_session
            self.then_stream_still_delivers(self.newer, self.websockets[-1])
        finally:
            self.cleanup_streams()

    def test_overlapping_streams_in_one_conversation_keep_their_own_context(self, monkeypatch):
        self.given_fake_websockets_and_client(monkeypatch)
        try:
            self.when_two_streams_overlap()
            self.then_text_and_ids_remain_stream_scoped()
        finally:
            self.cleanup_streams()

    def test_legacy_messages_keep_the_existing_event_data_shape(self, monkeypatch):
        self.given_fake_websockets_and_client(monkeypatch)
        try:
            self.when_a_legacy_stream_is_sent()
            self.then_legacy_messages_are_unchanged()
        finally:
            self.cleanup_streams()

    def test_client_instances_do_not_share_stream_sessions(self, monkeypatch):
        self.given_fake_websockets_and_client(monkeypatch)
        other_client = sse_client.SSEClient("other", Mock(), "wss://example.invalid")
        assert self.client.sessions is not other_client.sessions

    def test_streamer_queue_passes_its_request_logger_to_the_stream(self, monkeypatch):
        self.given_fake_websockets_and_client(monkeypatch)
        self.queue = sse_client.StreamerQueue(self.client, "conversation", "fallback", self.request_logger("request-1"))
        try:
            self.queue.setup_client({}, None, None)
            assert self.queue._setup_done.wait(1)
            self.records.append(self.client.sessions["conversation"])
            self.queue.enqueue("unchanged text ")
            self.queue.please_stop(end_stream=True)
            self.queue.join(2)
            assert not self.queue.is_alive()
            messages = self.websockets[0].messages
            assert messages[0]["data"] == "unchanged text "
            assert messages[0]["correlation"]["request_id"] == "request-1"
        finally:
            self.queue._setup_done.set()
            self.queue.please_stop()
            self.queue.join(1)
            self.cleanup_streams()

    def given_fake_websockets_and_client(self, monkeypatch):
        self.websockets = []
        self.records = []

        def create_websocket():
            connection = FakeWebSocket()
            self.websockets.append(connection)
            return connection

        monkeypatch.setattr(sse_client.websocket, "WebSocket", create_websocket)
        self.client = sse_client.SSEClient("test", Mock(), "wss://example.invalid")
        prepare_thread = self.client._prepare_streamer_thread

        def record_stream(session_id, streamer_session=None):
            self.records.append(streamer_session)
            return prepare_thread(session_id, streamer_session)

        monkeypatch.setattr(self.client, "_prepare_streamer_thread", record_stream)

    def given_an_active_stream(self):
        self.first = self.client.open_session("conversation", logger=self.request_logger("request-1"))

    def given_two_blocked_connections(self, monkeypatch, fail):
        self.connection_entered = [Event(), Event()]
        self.connection_release = [Event(), Event()]
        self.open_errors = []
        self.opened_streams = []

        def connect(socket, url, timeout):
            index = self.websockets.index(socket) - 1
            self.connection_entered[index].set()
            assert self.connection_release[index].wait(2)
            if fail:
                raise RuntimeError("connection unavailable")

        monkeypatch.setattr(FakeWebSocket, "connect", connect)

    def open_blocked_stream(self, request_id):
        try:
            self.opened_streams.append(self.client.open_session("conversation", logger=self.request_logger(request_id)))
        except RuntimeError as error:
            self.open_errors.append(error)

    def release_connections_and_cleanup(self, readers):
        for release in self.connection_release:
            release.set()
        for reader in readers:
            if reader.ident is not None:
                reader.join(1)
        self.cleanup_streams()

    def given_connection_failure(
        self, monkeypatch, close_fails=False, failure_point="connect", open_newer_stream=False
    ):
        self.connection_error = RuntimeError("connection unavailable")
        self.failed_record = None
        original_connect = FakeWebSocket.connect

        def fail_connection(socket, url, timeout):
            if open_newer_stream and self.failed_record is not None:
                return original_connect(socket, url, timeout)
            self.failed_record = self.records[-1]
            self.failed_socket = socket
            if close_fails:
                socket.close = Mock(side_effect=[RuntimeError("close unavailable"), None])
            if open_newer_stream:
                self.newer = self.client.open_session("conversation", logger=self.request_logger("request-3"))
            raise self.connection_error

        def fail_constructor():
            self.failed_record = self.records[-1]
            self.failed_socket = None
            raise self.connection_error

        monkeypatch.setattr(FakeWebSocket, "connect", fail_connection)
        if failure_point == "construct":
            monkeypatch.setattr(sse_client.websocket, "WebSocket", fail_constructor)

    def when_open_fails(self):
        with pytest.raises(RuntimeError, match="connection unavailable") as raised:
            self.client.open_session("conversation", logger=self.request_logger("request-2"))
        assert raised.value is self.connection_error

    def then_failed_stream_is_stopped(self):
        assert not self.failed_record["streamer_thread"].is_alive()
        if self.failed_socket is not None:
            try:
                self.failed_socket.close.assert_called_once_with()
            except AttributeError:
                assert self.failed_socket.closed

    def then_stream_still_delivers(self, stream, socket):
        self.client.stream_chunk(stream, "still healthy ")
        self.client.flush_stream(stream)
        assert socket.messages[0]["data"] == "still healthy "

    @staticmethod
    def request_logger(request_id):
        return structlog.get_logger("synthetic-streamer").bind(
            correlation_id=request_id,
            request_id=request_id,
            session_id="conversation",
            utterance_id=f"utterance-{request_id}",
            turn_id=1,
            attempt_id=f"attempt-{request_id}"
        )

    def when_two_streams_overlap(self):
        first_logger = self.request_logger("request-1")
        self.first = self.client.open_session("conversation", logger=first_logger)
        self.records.append(self.client.sessions["conversation"])
        self.second = self.client.open_session("conversation", logger=self.request_logger("request-2"))
        self.records.append(self.client.sessions["conversation"])
        structlog.get_context(first_logger)["utterance_id"] = "mutated-after-open"
        self.client.stream_chunk(self.first, "first ")
        self.client.stream_chunk(self.second, "second ")
        for stream in (self.first, self.second):
            self.client.flush_stream(stream)
            self.client.end_stream(stream)
            self.client.close_session(stream)

    def when_a_legacy_stream_is_sent(self):
        self.client.open_session("conversation")
        self.records.append(self.client.sessions["conversation"])
        self.client.stream_chunk("conversation", "legacy ")
        self.client.flush_stream("conversation")
        self.client.end_stream("conversation")

    def then_text_and_ids_remain_stream_scoped(self):
        assert self.first.stream_id != self.second.stream_id
        for websocket, request_id, text in zip(self.websockets, ("request-1", "request-2"), ("first ", "second ")):
            chunk, completion = websocket.messages
            assert chunk["event"] == "STREAMING_CHUNK"
            assert chunk["data"] == text
            assert completion["event"] == "STREAMING_DONE"
            assert chunk["stream_id"] == completion["stream_id"]
            assert chunk["correlation"]["request_id"] == request_id
            assert chunk["correlation"]["utterance_id"] == f"utterance-{request_id}"
            assert completion["correlation"] == chunk["correlation"]

    def then_legacy_messages_are_unchanged(self):
        assert self.websockets[0].messages == [{
            "event": "STREAMING_CHUNK",
            "data": "legacy "
        }, {
            "event": "STREAMING_DONE"
        }]

    def cleanup_streams(self):
        for record in self.records:
            record["chunk_joiner"].last_chunk_sent()
            if record["streamer_thread"].ident is not None:
                record["streamer_thread"].join(1)
        for websocket in self.websockets:
            websocket.close()


class FakeWebSocket:
    def __init__(self):
        self.messages = []
        self.closed = False

    def connect(self, url, timeout):
        return None

    def send(self, message):
        self.messages.append(json.loads(message))

    def close(self):
        self.closed = True
