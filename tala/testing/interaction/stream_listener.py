import threading
import time

import requests

from tala.utils.func import getenv

STREAM_CONNECT_TIMEOUT = 5.0
STREAM_COMPLETION_TIMEOUT = 10.0
STREAM_SHUTDOWN_TIMEOUT = 1.0


class StreamListenerError(RuntimeError):
    pass


class StreamListenerTimeoutError(TimeoutError):
    pass


class StreamListener(threading.Thread):
    SSE_BROKER_ENDPOINT_HTTPS = getenv("SSE_BROKER_ENDPOINT_HTTPS", default="")

    def __init__(self, streamer_url, session_id, logger):
        self._streamer_url = streamer_url
        self.current_data = None
        self.current_event = None
        self.stream_started = threading.Event()
        self._please_stop = threading.Event()
        self._stopped = threading.Event()
        self._session_id = session_id
        self._streaming_started = None
        self._streaming_ended = None
        self._logger = logger
        self._streamed_messages = []
        self._response = None
        self._stream_error = None
        self._stream_error_is_timeout = False
        super().__init__(daemon=True)

    def run(self):
        url = f"{self._streamer_url}/{self._session_id}"
        try:
            with requests.get(
                url, stream=True, timeout=(STREAM_CONNECT_TIMEOUT, STREAM_COMPLETION_TIMEOUT)
            ) as response:
                self._response = response
                response.raise_for_status()
                self.stream_started.set()
                self._logger.info("listening to stream", url=url)
                if self._please_stop.is_set():
                    return
                for line in response.iter_lines():
                    if self._please_stop.is_set():
                        break
                    if line:  # filter out keep-alive new lines
                        self.process_line(line.decode("utf-8"))
                    if self._please_stop.is_set():
                        break
        except requests.Timeout as error:
            if not self._please_stop.is_set():
                self._stream_error = error
                self._stream_error_is_timeout = True
                self._logger.exception("stream listener timed out", session_id=self._session_id, url=url)
        except Exception as error:
            if not self._please_stop.is_set():
                self._stream_error = error
                self._logger.exception("stream listener failed", session_id=self._session_id, url=url)
        finally:
            # Wake startup waiters when connection establishment fails as well.
            self.stream_started.set()
            self._response = None
            self._stopped.set()
            self._logger.info(
                "stream listener stopped listening, stream closed", received_messages=self._streamed_messages
            )

    def wait_until_started(self, timeout=STREAM_CONNECT_TIMEOUT):
        if not self.stream_started.wait(timeout):
            self.stop()
            raise StreamListenerTimeoutError(
                f"Timed out after {timeout:g}s waiting for the SSE connection for session {self._session_id}"
            )
        self._raise_stream_error()

    def _wait_for_completion(self):
        if not self._stopped.wait(STREAM_COMPLETION_TIMEOUT):
            self._logger.warning(
                "stream listener timed out waiting for completion",
                session_id=self._session_id,
                timeout_seconds=STREAM_COMPLETION_TIMEOUT,
            )
            self.stop()
            raise StreamListenerTimeoutError(
                f"Timed out after {STREAM_COMPLETION_TIMEOUT:g}s waiting for stream completion "
                f"(STREAMING_DONE) for session {self._session_id}"
            )
        self._raise_stream_error()
        if self._streaming_ended is None:
            raise StreamListenerError(f"The SSE connection closed before STREAMING_DONE for session {self._session_id}")

    def _raise_stream_error(self):
        if self._stream_error is None:
            return
        if self._stream_error_is_timeout:
            raise StreamListenerTimeoutError(f"The SSE request timed out for session {self._session_id}") \
                from self._stream_error
        raise StreamListenerError(f"The SSE request failed for session {self._session_id}") from self._stream_error

    def process_line(self, line):
        def is_event():
            return line.startswith("event: ")

        def is_data():
            return line.startswith("data: ")

        def extract_event():
            return line[len("event: "):]

        def extract_data():
            return line[len("data: "):]

        self._logger.info("stream listener processing line", line=line)
        if is_event():
            self.current_event = extract_event()
        if is_data() and self.current_event:
            self.current_data = extract_data()
            self.create_event_and_store()

    def create_event_and_store(self):
        event = None
        if self.current_event == "STREAMING_DONE":
            event = {"event": self.current_event}
            self._streaming_ended = time.time()
            self.please_stop()
        elif self.current_event == "STREAMING_CHUNK":
            if not bool(self._streaming_started):
                self._streaming_started = time.time()

            event = {"event": self.current_event, "data": self.current_data}
        if event:
            self._streamed_messages.append(event)
        self.current_event = None

    def please_stop(self):
        self._please_stop.set()

    def stop(self):
        self.please_stop()
        if self._response is not None:
            self._response.close()
        if self.is_alive() and threading.current_thread() is not self:
            self.join(STREAM_SHUTDOWN_TIMEOUT)

    @property
    def payload(self):
        self._wait_for_completion()
        return self._streamed_messages

    @property
    def system_utterance(self):
        utterance = ""
        for item in self.payload:
            try:
                utterance += item["data"]
            except KeyError:
                pass
        return utterance.strip()

    @property
    def streaming_started(self):
        return self._streaming_started

    @property
    def streaming_ended(self):
        return self._streaming_ended
