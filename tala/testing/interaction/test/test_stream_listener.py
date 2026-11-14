from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import Mock

import structlog

from tala.testing.interaction import stream_listener
from tala.testing.interaction.stream_listener import StreamListener

logger = structlog.get_logger("test-logger")


class ControlledStreamResponse:
    def __init__(self, send_initial_chunk, send_completion):
        self._send_initial_chunk = send_initial_chunk
        self._send_completion = send_completion
        self.release_producer = threading.Event()
        self.iteration_started = threading.Event()
        self.closed = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, _exception_type, _exception, _traceback):
        self.close()

    def raise_for_status(self):
        pass

    def iter_lines(self):
        self.iteration_started.set()
        if self._send_initial_chunk:
            yield b"event: STREAMING_CHUNK"
            yield b"data: Partial "
        self.release_producer.wait(2)
        if self._send_completion:
            yield b"event: STREAMING_CHUNK"
            yield b"data: delayed menu."
            yield b"event: STREAMING_DONE"
            yield b"data: "

    def close(self):
        self.closed.set()
        self.release_producer.set()


class ObservableEvent:
    def __init__(self):
        self._event = threading.Event()
        self.wait_started = threading.Event()

    def wait(self, timeout=None):
        self.wait_started.set()
        return self._event.wait(timeout)

    def set(self):
        self._event.set()


class TestStreamListener:
    def test_quotes_in_streamed_chunk(self):
        self.given_stream_listener()
        self.given_chunk('this contains "quotes".')
        self.when_chunk_processed()
        self.then_chunk_available({"event": "STREAMING_CHUNK", "data": 'this contains "quotes".'})

    def given_stream_listener(self):
        self._listener = StreamListener("some-url", "some-session-id", logger)

    def given_chunk(self, chunk):
        self._chunk = chunk

    def when_chunk_processed(self):
        self._listener.process_line("event: STREAMING_CHUNK")
        self._listener.process_line(f"data: {self._chunk}")

    def then_chunk_available(self, expected_chunk):
        assert expected_chunk in self._listener._streamed_messages


class TestStreamListenerCompletion:
    def given_controlled_stream(self, monkeypatch, send_initial_chunk, send_completion, timeout):
        self._response = ControlledStreamResponse(send_initial_chunk, send_completion)
        self._completion_event = ObservableEvent()
        self._listener = StreamListener("https://example.invalid/events", "test-session", logger)
        self._listener._stopped = self._completion_event
        monkeypatch.setattr(stream_listener.requests, "get", Mock(return_value=self._response))
        monkeypatch.setattr(stream_listener, "STREAM_COMPLETION_TIMEOUT", timeout, raising=False)
        # Model the previous short payload wait to keep this regression fast.
        monkeypatch.setattr(stream_listener, "TIMEOUT", 0.01, raising=False)

    def when_listener_starts(self):
        self._listener.start()
        assert self._listener.stream_started.wait(1)
        assert self._response.iteration_started.wait(1)

    def test_waits_for_delayed_stream_completion_before_returning_text(self, monkeypatch):
        self.given_controlled_stream(monkeypatch, send_initial_chunk=False, send_completion=True, timeout=1.0)
        self.when_listener_starts()
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(lambda: self._listener.system_utterance)
        release = None
        try:
            assert self._completion_event.wait_started.wait(1)
            assert not future.done()
            release = threading.Timer(0.05, self._response.release_producer.set)
            release.start()
            self._utterance = future.result(timeout=2)
        finally:
            if release:
                release.cancel()
            self._response.close()
            self._listener.join(1)
            pool.shutdown(wait=True)
        self.then_complete_delayed_text_is_returned()

    def then_complete_delayed_text_is_returned(self):
        assert self._utterance == "delayed menu."
        assert self._listener.streaming_ended is not None
        assert not self._listener.is_alive()

    def test_missing_stream_times_out_and_closes_listener(self, monkeypatch):
        self.given_controlled_stream(monkeypatch, send_initial_chunk=False, send_completion=False, timeout=0.01)
        self.when_listener_starts()
        self.when_system_utterance_is_read()
        self.then_stream_completion_timeout_is_reported()
        self.then_listener_is_closed()

    def when_system_utterance_is_read(self):
        self._error = None
        try:
            self._utterance = self._listener.system_utterance
        except TimeoutError as error:
            self._error = error
        finally:
            self._response.close()
            self._listener.join(1)

    def then_stream_completion_timeout_is_reported(self):
        assert self._error is not None
        assert "completion" in str(self._error)

    def then_listener_is_closed(self):
        assert self._response.closed.is_set()
        assert not self._listener.is_alive()
