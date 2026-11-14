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
        self.wait_timeout = None

    def wait(self, timeout=None):
        self.wait_timeout = timeout
        self.wait_started.set()
        return self._event.wait(timeout)

    def set(self):
        self._event.set()


class DelayedHeadersRequest:
    def __init__(self, response):
        self._response = response
        self.started = threading.Event()
        self.release_headers = threading.Event()
        self.timeout = None

    def __call__(self, _url, stream, timeout):
        self.timeout = timeout
        self.started.set()
        if not self.release_headers.wait(timeout[1]):
            raise stream_listener.requests.ReadTimeout("response headers timed out")
        return self._response


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
    def test_waits_for_response_headers_within_request_timeout_bounds(self, monkeypatch):
        self.given_delayed_response_headers(monkeypatch)
        self.when_waiting_for_stream_start(release_headers=True)
        self.then_stream_started_with_bounded_request_timeouts()

    def given_delayed_response_headers(self, monkeypatch):
        monkeypatch.setattr(stream_listener, "STREAM_CONNECT_TIMEOUT", 0.01)
        monkeypatch.setattr(stream_listener, "STREAM_READ_TIMEOUT", 0.2)
        monkeypatch.setattr(stream_listener, "STREAM_COMPLETION_TIMEOUT", 0.2)
        monkeypatch.setattr(stream_listener, "STREAM_SHUTDOWN_TIMEOUT", 0.1)
        monkeypatch.setattr(stream_listener, "STREAM_START_TIMEOUT", 0.31)
        self._response = ControlledStreamResponse(send_initial_chunk=False, send_completion=False)
        self._request = DelayedHeadersRequest(self._response)
        monkeypatch.setattr(stream_listener.requests, "get", self._request)
        self._listener = StreamListener("https://example.invalid/events", "test-session", logger)
        self._startup_event = ObservableEvent()
        self._listener.stream_started = self._startup_event

    def when_waiting_for_stream_start(self, release_headers):
        self._listener.start()
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._listener.wait_until_started)
        release = None
        self._request_started = self._request.started.wait(1)
        self._start_error = None
        try:
            if release_headers:
                release = threading.Timer(0.05, self._request.release_headers.set)
                release.start()
            try:
                future.result(timeout=1)
            except stream_listener.StreamListenerTimeoutError as error:
                self._start_error = error
        finally:
            if release:
                release.cancel()
            self._listener.stop()
            self._listener.join(1)
            pool.shutdown(wait=True)

    def then_stream_started_with_bounded_request_timeouts(self):
        assert self._request_started
        assert self._start_error is None
        assert stream_listener.STREAM_START_TIMEOUT > (
            stream_listener.STREAM_CONNECT_TIMEOUT + stream_listener.STREAM_READ_TIMEOUT
        )
        assert self._startup_event.wait_timeout == stream_listener.STREAM_START_TIMEOUT
        assert self._request.timeout == (stream_listener.STREAM_CONNECT_TIMEOUT, stream_listener.STREAM_READ_TIMEOUT)
        assert not self._listener.is_alive()

    def test_response_header_timeout_stops_listener_before_reporting_failure(self, monkeypatch):
        self.given_delayed_response_headers(monkeypatch)
        self.when_waiting_for_stream_start(release_headers=False)
        self.then_stream_start_timeout_is_reported_and_listener_is_closed()

    def then_stream_start_timeout_is_reported_and_listener_is_closed(self):
        assert self._request_started
        assert self._start_error is not None
        assert "timed out" in str(self._start_error).lower()
        assert not self._listener.is_alive()

    def test_waits_for_delayed_stream_completion_before_returning_text(self, monkeypatch):
        self.given_controlled_stream(monkeypatch, send_initial_chunk=False, send_completion=True, timeout=1.0)
        self.when_listener_starts()
        self.when_delayed_stream_is_consumed()
        self.then_complete_delayed_text_is_returned()

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
        self._stream_started = self._listener.stream_started.wait(1)
        self._iteration_started = self._response.iteration_started.wait(1)

    def when_delayed_stream_is_consumed(self):
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(lambda: self._listener.system_utterance)
        release = None
        self._completion_wait_started = self._completion_event.wait_started.wait(1)
        self._future_pending_before_release = not future.done()
        try:
            release = threading.Timer(0.05, self._response.release_producer.set)
            release.start()
            self._utterance = future.result(timeout=2)
        finally:
            if release:
                release.cancel()
            self._response.close()
            self._listener.join(1)
            pool.shutdown(wait=True)

    def then_complete_delayed_text_is_returned(self):
        assert self._stream_started
        assert self._iteration_started
        assert self._completion_wait_started
        assert self._future_pending_before_release
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
