import structlog
import time
import queue
import threading
import random
import uuid

import pytest

from tala.utils.sse_client import AbstractSSEClient, SSEClient, ChunkJoiner, StreamerQueue
from tala.utils.func import configure_stdout_logging, getenv

logger = structlog.get_logger(__name__)
log_level = getenv("LOG_LEVEL", default="DEBUG")
configure_stdout_logging(log_level)


def resolve_streamer_endpoint():
    endpoint = str(getenv("SSE_BROKER_ENDPOINT_WSS", default="") or "")
    if endpoint:
        return endpoint
    https_endpoint = str(getenv("SSE_BROKER_ENDPOINT_HTTPS", default="") or "")
    if https_endpoint.startswith("https://"):
        return f"wss://{https_endpoint[len('https://'):]}"
    if https_endpoint.startswith("http://"):
        return f"ws://{https_endpoint[len('http://'):]}"
    return ""


class TestSSEClient:
    def setup_method(self):
        pass

    def test_creation(self):
        self.given_args_for_client_creation(["", logger, "some_endpoint", 443])
        self.when_sse_client_created()
        self.then_client_created_with(logger, "some_endpoint", 443, "name_base")

    def given_args_for_client_creation(self, args):
        self._sse_args = args

    def when_sse_client_created(self):
        self._sse_client = SSEClient(*self._sse_args)

    def then_client_created_with(self, logger, endpoint, port, name_base):
        assert self._sse_client.logger == logger
        assert self._sse_client._endpoint == endpoint
        assert self._sse_client._port == port

    @pytest.mark.skip("SSE Service down")
    @pytest.mark.parametrize("chunk", ["This is an unproblematic test utterance.", "Frölunda ", "Fr\u00f6lunda"])
    def test_stream_single_chunk(self, chunk):
        self.given_streamer_endpoint()
        self.given_sse_client_started("test_client", logger, self._endpoint, 443)
        self.given_session_id("test-session-id")
        self.when_chunk_streamed(chunk)
        self.then_everything_is_ok()

    def given_sse_client_started(self, name, logger, endpoint, port):
        self._client = SSEClient(name, logger, endpoint, port)
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

    def then_everything_is_ok(self):
        assert True

    @pytest.mark.skip("SSE Service down")
    def test_multi_sessions_single_client_no_message_confusion(self):
        self.given_mocked_stream_to_frontend()
        self.given_single_client()
        self.when_client_streaming_to_num_sessions(10)
        self.then_all_streams_correct()

    def given_mocked_stream_to_frontend(self):
        test_self = self

        def mocked_stream_to_frontend(self, streamer_session, message):
            session_id = streamer_session["session_id"]
            if session_id not in test_self._streams:
                test_self._streams[session_id] = []
            test_self._streams[session_id].append(message)

        self._streams = {}
        SSEClient._stream_to_frontend = mocked_stream_to_frontend

    def given_single_client(self):
        print("create client")
        self.given_streamer_endpoint()
        self._client = SSEClient(
            "some-id",
            logger,
            self._endpoint,
            443,
        )
        print("client created")

    def given_streamer_endpoint(self):
        self._endpoint = resolve_streamer_endpoint()
        assert self._endpoint, "SSE_BROKER_ENDPOINT_WSS or SSE_BROKER_ENDPOINT_HTTPS not set"

    def when_client_streaming_to_num_sessions(self, num_sessions):
        for i in range(0, num_sessions):
            session_id = f"session-{i}"
            print("open session for session id", session_id)
            self._client.open_session(session_id)

        for round in range(0, 4):
            print("round", round)
            for i in random.sample(range(0, num_sessions), num_sessions):
                print("stream to", i)
                self._client.stream_chunk(f"session-{i}", f"session-{i} ")

        for i in range(0, num_sessions):
            print("close stream", i)
            client = self._client
            client.flush_stream(f"session-{i}")
            client.end_stream(f"session-{i}")
            client.close_session(f"session-{i}")
            print("done")

    def then_all_streams_correct(self):
        for session_id, streamed in self._streams.items():
            for item in streamed:
                if item["event"] == "STREAMING_CHUNK":
                    assert session_id + " " == item["data"]


class RecordingSSEClient(AbstractSSEClient):
    def __init__(self):
        super().__init__("test-client", logger, "wss://example.org")
        self.sessions = {}
        self.messages = queue.Queue()

    def _stream_to_frontend(self, streamer_session, message):
        self.messages.put(message)


class TestPronunciationReplacementStreaming:
    def test_disabled_replacements_pass_chunks_through_before_flush(self, monkeypatch):
        self.given_client(monkeypatch, "false", {"Hello": "Howdy"})
        self.when_session_opened()
        self.when_chunk_streamed("Hel")
        self.when_chunk_streamed("lo")
        self.then_chunks_are_delivered_in_order_before_flush(["Hel", "lo"])

    def test_empty_replacement_model_passes_chunks_through_before_flush(self, monkeypatch):
        self.given_client(monkeypatch, "true", {})
        self.when_session_opened()
        self.when_chunk_streamed("Hello")
        self.then_chunks_are_delivered_in_order_before_flush(["Hello"])

    def test_default_keeps_existing_replacement_behavior(self, monkeypatch):
        self.given_client(monkeypatch, None, {"Hello": "Howdy"})
        self.when_session_opened()
        self.when_chunk_streamed("Hello ")
        self.when_stream_flushed()
        self.then_streamed_text_is("Howdy ")

    def given_client(self, monkeypatch, setting, replacement_model):
        if setting is None:
            monkeypatch.delenv("PRONUNCIATION_REPLACEMENTS_ENABLED", raising=False)
        else:
            monkeypatch.setenv("PRONUNCIATION_REPLACEMENTS_ENABLED", setting)
        self._client = RecordingSSEClient()
        self._replacement_model = replacement_model
        self._session_id = str(uuid.uuid4())

    def when_session_opened(self):
        self._client.open_session(self._session_id, self._replacement_model)

    def when_chunk_streamed(self, chunk):
        self._client.stream_chunk(self._session_id, chunk)

    def when_stream_flushed(self):
        self._client.flush_stream(self._session_id)

    def then_chunks_are_delivered_in_order_before_flush(self, expected_chunks):
        try:
            actual_chunks = [self._client.messages.get(timeout=0.5)["data"] for _ in expected_chunks]
            assert actual_chunks == expected_chunks
        finally:
            self.when_stream_flushed()
        assert self._client.sessions[self._session_id]["streamed"] == expected_chunks

    def then_streamed_text_is(self, expected_text):
        assert self._client.sessions[self._session_id]["streamed"] == [expected_text]


class FailingSSEClient:
    sessions = {"test-session": {"streamed": []}}

    def open_session(self, _session_id, _s_and_r_dict=None, _logger=None):
        raise RuntimeError("boom")

    def set_persona(self, _session_id, _persona):
        pass

    def set_voice(self, _session_id, _voice):
        pass

    def stream_chunk(self, _session_id, _chunk):
        pass

    def flush_stream(self, _session_id):
        pass

    def end_stream(self, _session_id):
        pass

    def close_session(self, _session_id):
        pass


class TestStreamerQueueSetupFailure:
    def test_setup_done_signaled_on_open_session_failure(self):
        self.given_streamer_queue_with_failing_client()
        self.when_setup_client_called()
        self.then_setup_done_is_signaled()

    def given_streamer_queue_with_failing_client(self):
        self._queue = StreamerQueue(FailingSSEClient(), "test-session", "default", logger)

    def when_setup_client_called(self):
        try:
            self._queue.setup_client({}, "persona", "voice")
            self._setup_done = self._queue._setup_done.wait(timeout=0.2)
        finally:
            self._queue._setup_done.set()
            self._queue.please_stop(end_stream=False)
            self._queue.join(timeout=0.2)

    def then_setup_done_is_signaled(self):
        assert self._setup_done, "setup_client should signal setup completion even on failure"


class TestStreamerThreadsDaemon:
    def test_streamer_queue_is_daemon(self):
        self.given_streamer_queue()
        self.then_streamer_queue_is_daemon()

    def test_setup_client_uses_daemon_thread(self):
        self.given_streamer_queue()
        self.when_setup_client_called()
        self.then_setup_thread_is_daemon()

    def test_streamer_thread_is_daemon(self):
        self.given_sse_client()
        self.when_streamer_thread_prepared()
        self.then_streamer_thread_is_daemon()

    def given_streamer_queue(self):
        self._queue = StreamerQueue(FailingSSEClient(), "test-session", "default", logger)

    def given_sse_client(self):
        self._client = SSEClient("test-client", logger, "wss://example.org", 443)

    def when_setup_client_called(self):
        try:
            self._queue.setup_client({}, "persona", "voice")
            self._setup_done = self._queue._setup_done.wait(timeout=0.2)
        finally:
            self._queue._setup_done.set()
            self._queue.please_stop(end_stream=False)
            self._queue.join(timeout=0.2)

    def when_streamer_thread_prepared(self):
        self._streamer_thread, self._chunk_joiner = self._client._prepare_streamer_thread("session-id")

    def then_streamer_queue_is_daemon(self):
        assert self._queue.daemon is True

    def then_setup_thread_is_daemon(self):
        assert self._queue._setup_thread.daemon is True

    def then_streamer_thread_is_daemon(self):
        assert self._streamer_thread.daemon is True


class TestChunkJoiner:
    def test_single_chunk(self):
        self.given_joiner()
        self.given_chunks(["hej"])
        self.then_resulting_chunks_are(["hej"])

    def given_joiner(self):
        self._joiner = ChunkJoiner(logger)

    def given_chunks(self, chunks):
        def produce_chunks():
            for chunk in chunks:
                time.sleep(random.uniform(0.0, 0.2))
                self._joiner.add_chunk(chunk)
            self.when_end_chunks()

        self.producer_thread = threading.Thread(target=produce_chunks)
        self.producer_thread.start()

    def when_end_chunks(self):
        self._joiner.last_chunk_sent()

    def then_resulting_chunks_are(self, expected_chunks):
        self._result = list(self._joiner)
        assert len(expected_chunks) == len(self._result), f"{len(expected_chunks)} != {len(self._result)}"
        for expected, actual in zip(expected_chunks, self._result):
            assert expected == actual

    def test_two_chunks(self):
        self.given_joiner()
        self.given_chunks(["hej", " kalle"])
        self.then_resulting_chunks_are(["hej", " kalle"])

    def test_two_chunks_should_be_joined_if_no_initial_space(self):
        self.given_joiner()
        self.given_chunks(["hej", "san"])
        self.then_resulting_chunks_are(["hejsan"])

    def test_three_chunks_should_be_joined_if_no_initial_space(self):
        self.given_joiner()
        self.given_chunks(["hej", "san", "sa"])
        self.then_resulting_chunks_are(["hejsansa"])

    def test_two_chunks_should_be_joined_when_third_has_initial_space(self):
        self.given_joiner()
        self.given_chunks(["hej", "san", " sa", " kalle"])
        self.then_resulting_chunks_are(["hejsan", " sa", " kalle"])

    def test_naturalistic_gpt_output(self):
        self.given_joiner()
        self.given_chunks([
            "En", " lust", "j", "akt", " är", " en", " b", "åt", " som", " används", " för", " nö", "jes", "seg",
            "ling", ". "
        ])
        self.then_resulting_chunks_are([
            "En", " lustjakt", " är", " en", " båt", " som", " används", " för", " nöjessegling. "
        ])

    def test_ndg_system_case(self):
        self.given_joiner()
        self.given_chunks(["Har du några fler frågor? "])
        self.then_resulting_chunks_are(["Har du några fler frågor? "])

    def test_ndg_system_case_no_space(self):
        self.given_joiner()
        self.given_chunks(["Har du några fler frågor?"])
        self.then_resulting_chunks_are(["Har du några fler frågor?"])
