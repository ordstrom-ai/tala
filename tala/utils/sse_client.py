import json
from contextlib import suppress
import os
import queue
import threading
import uuid

import websocket
import requests
import structlog

from tala.utils.log_context import validated_correlation_context

STREAMING_DONE = "STREAMING_DONE"
STREAMING_SET_PERSONA = "STREAMING_SET_PERSONA"
STREAMING_SET_VOICE = "STREAMING_SET_VOICE"
STREAMING_CHUNK = "STREAMING_CHUNK"
TIMEOUT = 5.0
PRONUNCIATION_REPLACEMENTS_ENABLED = "PRONUNCIATION_REPLACEMENTS_ENABLED"
_FALSE_VALUES = {"0", "false", "no", "off"}


class SSEClientException(BaseException):
    pass


class StreamIteratorException(BaseException):
    pass


class SSEStreamHandle:
    """A particular producer stream, independent of the conversation's latest stream."""
    def __init__(self, streamer_session):
        self.streamer_session = streamer_session

    @property
    def stream_id(self):
        return self.streamer_session["stream_id"]

    @property
    def session_id(self):
        return self.streamer_session["session_id"]


class AbstractSSEClient:
    def __init__(self, client_id_base, logger, endpoint, port=None):
        self._setup_logger(logger)
        self._endpoint = endpoint
        if port:
            self._port = int(port)
        else:
            self._port = 443
        self._client_id = f"{client_id_base}-{str(uuid.uuid4())}"

    def _setup_logger(self, logger):
        self._base_logger = logger
        self._set_logger(logger)

    def _set_logger(self, logger):
        self.logger = logger

    def _reset_logger(self):
        self._set_logger(self._base_logger)

    def start(self):
        pass

    @property
    def client_id(self):
        return self._client_id

    def _get_topic(self, streamer_session):
        return f'tm/{streamer_session["session_id"]}'

    def _pronunciation_replacements_enabled(self):
        setting = os.getenv(PRONUNCIATION_REPLACEMENTS_ENABLED, "true")
        return setting.strip().lower() not in _FALSE_VALUES

    def open_session(self, session_id, s_and_r_dict=None, logger=None):
        self._open_streamer_session(session_id, s_and_r_dict, logger)

    def _open_streamer_session(self, session_id, s_and_r_dict=None, logger=None):
        streamer_session = self._create_streamer_session(session_id, s_and_r_dict, logger)
        self.sessions[session_id] = streamer_session
        streamer_session["streamer_thread"].start()
        return streamer_session

    def _create_streamer_session(self, session_id, s_and_r_dict=None, logger=None):
        self.logger.debug("sse client open session", session_id=session_id)
        replacement_model = s_and_r_dict or {}
        if not self._pronunciation_replacements_enabled():
            replacement_model = {}
        streamer_session = {
            "session_id": session_id,
            "search_and_replace_dict": replacement_model,
            "message_counter": 0,
            "streamed": [],
            "logger": logger,
            "stream_id": str(uuid.uuid4()),
            "correlation": self._correlation_for_logger(logger),
        }
        streamer_thread, chunk_joiner = self._prepare_streamer_thread(session_id, streamer_session)
        streamer_session.update(streamer_thread=streamer_thread, chunk_joiner=chunk_joiner)
        return streamer_session

    @staticmethod
    def _correlation_for_logger(logger):
        if logger is None:
            return {}
        try:
            return validated_correlation_context(structlog.get_context(logger))
        except (AttributeError, TypeError):
            return {}

    def _streamer_session_for(self, session_id):
        try:
            return session_id.streamer_session
        except AttributeError:
            return self.sessions[session_id]

    def _apply_dictionary(self, session_id, chunk, streamer_session=None):
        def key_matches_beginning_of_chunk(key, chunk):
            return chunk.startswith(f"{key} ")

        def key_matches_middle_of_chunk(key, chunk):
            chunk_ends = [" ", ".", ",", "!", "?"]
            for end in chunk_ends:
                search_term = f" {key}{end}"
                if search_term in chunk:
                    return search_term

        def key_matches_end_of_chunk(key, chunk):
            return chunk.endswith(f" {key}")

        streamer_session = self._streamer_session_for(session_id) if streamer_session is None else streamer_session
        search_and_replace_dict = streamer_session["search_and_replace_dict"]
        stream_logger = streamer_session.get("logger") or self.logger

        if chunk in search_and_replace_dict:
            stream_logger.debug("Matched entire chunk", chunk=chunk)
            return search_and_replace_dict[chunk]
        for key in search_and_replace_dict:
            if key_matches_beginning_of_chunk(key, chunk):
                stream_logger.debug("Matched beginning of chunk", key=key, chunk=chunk)
                chunk = chunk.replace(key, search_and_replace_dict[key], 1)
            match = key_matches_middle_of_chunk(key, chunk)
            while match:
                stream_logger.debug("Matched middle of chunk", key=key, chunk=chunk)
                chunk = chunk.replace(key, search_and_replace_dict[key], 1)
                match = key_matches_middle_of_chunk(key, chunk)
            if key_matches_end_of_chunk(key, chunk):
                stream_logger.debug("Matched end of chunk", key=key, chunk=chunk)
                chunk = chunk.replace(key, search_and_replace_dict[key], 1)
        return chunk

    def _prepare_streamer_thread(self, session_id, apply_pronunciation_replacements=True, streamer_session=None):
        # Accept the positional stream record used by the correlation branch,
        # while retaining main's explicit positional/keyword mode argument.
        if streamer_session is None:
            try:
                replacement_model = apply_pronunciation_replacements["search_and_replace_dict"]
            except (TypeError, KeyError):
                pass
            else:
                streamer_session = apply_pronunciation_replacements
                apply_pronunciation_replacements = bool(replacement_model)

        def stream_chunks():
            self._streaming_exception = None
            stream = self._streamer_session_for(session_id) if streamer_session is None else streamer_session
            for chunk in stream["chunk_joiner"]:
                try:
                    chunk = self._apply_dictionary(session_id, chunk, stream)
                    self._stream_to_frontend(stream, {"event": STREAMING_CHUNK, "data": chunk})
                    stream["streamed"].append(chunk)
                except Exception as e:
                    stream["streaming_exception"] = e
                    stream_logger = stream.get("logger") or self.logger
                    stream_logger.exception("Exception raised in streamer thread")

        stream_logger = streamer_session.get("logger") if streamer_session is not None else None
        if apply_pronunciation_replacements:
            chunk_joiner = ChunkJoiner(stream_logger or self.logger)
        else:
            chunk_joiner = _PassThroughChunkJoiner(stream_logger or self.logger)
        streamer_thread = threading.Thread(target=stream_chunks, daemon=True)
        return streamer_thread, chunk_joiner

    def stream_utterance(self, session_id, persona=None, voice=None, utterance=""):
        self.set_persona(session_id, persona)
        self.set_voice(session_id, voice)
        self.stream_chunk(session_id, utterance + " ")

    def set_persona(self, session_id, persona):
        streamer_session = self._streamer_session_for(session_id)
        self._stream_to_frontend(streamer_session, {"event": STREAMING_SET_PERSONA, "data": persona if persona else ""})

    def set_voice(self, session_id, voice):
        streamer_session = self._streamer_session_for(session_id)
        self._stream_to_frontend(streamer_session, {"event": STREAMING_SET_VOICE, "data": voice if voice else ""})

    def stream_chunk(self, session_id, chunk):
        streamer_session = self._streamer_session_for(session_id)
        joiner = streamer_session["chunk_joiner"]
        joiner.add_chunk(chunk)

    def flush_stream(self, session_id):
        streamer_session = self._streamer_session_for(session_id)
        stream_logger = streamer_session.get("logger") or self.logger
        stream_logger.debug("flushing stream", stream_id=streamer_session["stream_id"])
        joiner = streamer_session["chunk_joiner"]
        joiner.last_chunk_sent()
        streamer_thread = streamer_session["streamer_thread"]
        streamer_thread.join(3.0)
        if streamer_thread.is_alive():
            stream_logger.warn("Streamer thread is still alive!", streamed=streamer_session["streamed"])

    def end_stream(self, session_id):
        streamer_session = self._streamer_session_for(session_id)
        stream_logger = streamer_session.get("logger") or self.logger
        stream_logger.debug("ending stream", stream_id=streamer_session["stream_id"])
        self._stream_to_frontend(streamer_session, {"event": STREAMING_DONE})


class StreamIterator:
    def __init__(self, session_id, base_url, logger):
        self.logger = logger
        self.url = f'{base_url}/{session_id}'
        self.response = None
        self.iterator = None

        self._current_event = None
        self._session_id = session_id
        self._stream = None

    def wait_for_message(self, expected_message):
        next_message = self.get_next_message()
        if json.loads(expected_message) != json.loads(next_message):
            self.logger.info("received unexpected message", expected=expected_message, received=next_message)
            raise SSEClientException(f"Expected '{expected_message}', but received '{next_message}'.")
        else:
            self.logger.info("received expected message", message=next_message)

    @property
    def session_id(self):
        return self._session_id

    def start_stream(self):
        """Start the streaming connection and prepare the iterator."""
        self.response = requests.get(self.url, stream=True)
        self.response.raise_for_status()  # Ensure the response is successful
        self.iterator = self.response.iter_lines()

    def get_next_message(self):
        """Retrieve the next message from the stream."""
        if self.iterator is None:
            raise RuntimeError("Stream has not been started. Call start_stream() first.")
        try:
            item = self._get_next_item()
            return item
        except StopIteration:
            return None

    def close_stream(self):
        if self.response:
            self.response.close()
            self.response = None

    def _get_next_item(self):
        def is_event(line):
            return line.startswith("event: ")

        def is_data(line):
            return line.startswith("data: ")

        def extract_event(line):
            return line[len("event: "):]

        def extract_data(line):
            return line[len("data: "):]

        while True:
            try:
                line = next(self.iterator).decode('utf-8')
            except AttributeError:
                raise StreamIteratorException("tried to read beyond end")

            if is_event(line):
                event = extract_event(line)
                if event == STREAMING_DONE:
                    self.close_stream()
                    return f'{{"event": "{event}"}}'
                elif event in [STREAMING_CHUNK, STREAMING_SET_PERSONA, STREAMING_SET_VOICE]:
                    while True:
                        next_line = next(self.iterator).decode('utf-8')
                        if is_data(next_line):
                            data = extract_data(next_line)
                            return f'{{"event": "{event}", "data": "{data.strip()}"}}'


class ChunkJoiner:
    """
    Iterates over segments put together from chunks received in the queue. A segment is not made available until we know
    that it's a complete segment. To be considered complete segment means that the next chunk starts with a space, or
    that someone called last_chunk_sent().
    """
    def __init__(self, logger):
        self.logger = logger
        self._chunk_queue = queue.Queue()
        self._received_last_chunk = threading.Event()
        self._next_chunk = None
        self._collected_chunks = []

    def add_chunk(self, chunk):
        self._chunk_queue.put(chunk)

    def last_chunk_sent(self):
        self._received_last_chunk.set()

    def __next__(self):
        return self._get_next_segment()

    def _get_next_segment(self):
        self._collected_chunks = []
        self._collect_chunks()
        if self._collected_chunks:
            next_segment = "".join(self._collected_chunks)
            self.logger.debug("Joiner collected segment", next_segment=next_segment)
            return next_segment
        else:
            self.logger.debug("No more chunks collected, stopping iteration")
            raise StopIteration

    def _collect_chunks(self):
        def waiting_for_first_chunk():
            return self._collected_chunks == []

        def add_next_chunk_to_collected_chunks():
            self._collected_chunks.append(self._next_chunk)
            self._next_chunk = None

        def next_chunk_belongs_to_this_segment():
            return not self._next_chunk.startswith(" ")

        def handle_possible_last_chunk():
            try:
                self._next_chunk = self._chunk_queue.get_nowait()
                if self._next_chunk:
                    self.logger.debug("there was a last chunk to handle.")
                    add_next_chunk_to_collected_chunks()
            except queue.Empty:
                pass

        while not self._complete_segment_collected():
            try:
                if not self._next_chunk:
                    self._next_chunk = self._chunk_queue.get(timeout=0.05)

                if waiting_for_first_chunk() or next_chunk_belongs_to_this_segment():
                    add_next_chunk_to_collected_chunks()

            except queue.Empty:
                if self._received_last_chunk.is_set():
                    self.logger.debug("received last chunk")
                    handle_possible_last_chunk()
                    break

    def _complete_segment_collected(self):
        def next_chunk_was_not_needed_to_complete_this_segment():
            return self._collected_chunks and self._next_chunk

        def collected_chunks_end_with_space():
            return self._collected_chunks and self._collected_chunks[-1].endswith(" ")

        return next_chunk_was_not_needed_to_complete_this_segment() or collected_chunks_end_with_space()

    def __iter__(self):
        return self


class _PassThroughChunkJoiner(ChunkJoiner):
    """Deliver each queued chunk as soon as it arrives, without word lookahead."""
    def _get_next_segment(self):
        while True:
            try:
                return self._chunk_queue.get(timeout=0.05)
            except queue.Empty:
                if self._received_last_chunk.is_set():
                    raise StopIteration


class SSEClient(AbstractSSEClient):
    sessions = {}

    def __init__(self, client_id_base, logger, endpoint, port=None):
        super().__init__(client_id_base, logger, endpoint, port)
        self.sessions = {}
        self._sessions_lock = threading.Lock()
        self._open_sequence = 0

    def set_persona(self, session_id, persona):
        if persona:
            super().set_persona(session_id, persona)

    def set_voice(self, session_id, voice):
        if voice:
            super().set_voice(session_id, voice)

    def open_session(self, session_id, s_and_r_dict=None, logger=None):
        with self._sessions_lock:
            self._open_sequence += 1
            open_sequence = self._open_sequence
        streamer_session = self._create_streamer_session(session_id, s_and_r_dict, logger)
        streamer_session["open_sequence"] = open_sequence
        session_websocket = None
        try:
            url = f"{self._endpoint}/{self._get_topic(streamer_session)}"
            stream_logger = streamer_session.get("logger") or self.logger
            stream_logger.info("create websocket", stream_id=streamer_session["stream_id"])
            session_websocket = websocket.WebSocket()
            stream_logger.info("connecting websocket to URL", url=url)
            session_websocket.connect(url, timeout=TIMEOUT)
            stream_logger.info("websocket connected", url=url)
            streamer_session["websocket"] = session_websocket
            streamer_session["streamer_thread"].start()
        except BaseException:
            # Failed/unready streams never enter the public session mapping.
            with suppress(Exception):
                streamer_session["chunk_joiner"].last_chunk_sent()
                streamer_session["streamer_thread"].join(timeout=1.0)
            if session_websocket is not None:
                with suppress(Exception):
                    session_websocket.close()
            raise
        with self._sessions_lock:
            current = self.sessions.get(session_id)
            if current is None or current.get("open_sequence", -1) < open_sequence:
                self.sessions[session_id] = streamer_session
        return SSEStreamHandle(streamer_session)

    def _stream_to_frontend(self, streamer_session, message):
        def remove_final_space(message):
            if "data" in message:
                message["data"] = message["data"].strip()
            return message

        streamer_session["message_counter"] += 1
        stream_logger = streamer_session.get("logger") or self.logger
        stream_logger.debug(
            "SSE Client streaming to frontend",
            message=message,
            session_id=streamer_session["session_id"],
            client_id=self.client_id,
            stream_id=streamer_session["stream_id"],
        )
        producer_message = dict(message)
        if streamer_session.get("correlation"):
            producer_message["stream_id"] = streamer_session["stream_id"]
            producer_message["correlation"] = dict(streamer_session["correlation"])
        streamer_session["websocket"].send(json.dumps(producer_message))

    def close_session(self, session_id):
        streamer_session = self._streamer_session_for(session_id)
        streamer_session["websocket"].close()
        streamer_exception = streamer_session.get("streaming_exception")
        if streamer_exception:
            raise SSEClientException(
                f'{streamer_exception} was raised during streaming in {streamer_session["session_id"]}. '
                f'Streamed: {streamer_session["streamed"]}.'
            ) from streamer_exception
        stream_logger = streamer_session.get("logger") or self.logger
        stream_logger.debug("close session", client_id=self.client_id, session_id=streamer_session["session_id"])
        stream_logger.info(
            "Streamed in session",
            num_messages=streamer_session["message_counter"],
            streamed=streamer_session["streamed"]
        )
        self._reset_logger()


END_STREAM_CHUNK = "[END STREAM]"


class StreamerQueue(threading.Thread):
    def __init__(self, sse_client, session_id, default_utterance, logger):
        super().__init__(daemon=True)
        self._actual_q = queue.Queue()
        self._sse_client = sse_client
        self._session_id = session_id
        self._stream_target = session_id
        self._setup_done = threading.Event()
        self._setup_failed = False
        self._setup_exception = None
        self._setup_thread = None
        self._end_stream = False
        self._default_utterance = default_utterance
        self._logger = logger
        self._streamed_in_session = []

    @property
    def session_id(self):
        return self._session_id

    @property
    def streamed_in_session(self):
        self.join()
        return self._streamed_in_session

    def setup_client(self, pronunciation_model, persona, voice):
        def setup():
            try:
                self.start()
                stream = self._sse_client.open_session(self.session_id, pronunciation_model, self._logger)
                self._stream_target = self.session_id if stream is None else stream
                self._sse_client.set_persona(self._stream_target, persona)
                self._sse_client.set_voice(self._stream_target, voice)
            except Exception as exc:
                self._setup_failed = True
                self._setup_exception = exc
                self._logger.exception("setup_client failed")
            finally:
                self._setup_done.set()
                self._logger.info("setup_client done", setup_failed=self._setup_failed)

        self._logger.info("setup_client")

        self._setup_thread = threading.Thread(target=setup, daemon=True)
        self._setup_thread.start()

    def enqueue(self, chunk):
        self._actual_q.put(chunk)

    def please_stop(self, end_stream=False):
        self._actual_q.put(END_STREAM_CHUNK)
        self._end_stream = end_stream

    def run(self):
        self._setup_done.wait()
        if self._setup_failed:
            self._streamed_in_session = []
            return
        streamed_messages = False
        while True:
            try:
                chunk = self._actual_q.get(timeout=0.01)
            except queue.Empty:
                chunk = None

            if chunk:
                if chunk == END_STREAM_CHUNK:
                    if not streamed_messages:
                        self._sse_client.stream_chunk(self._stream_target, self._default_utterance)
                    break
                streamed_messages = True
                self._sse_client.stream_chunk(self._stream_target, chunk)

        self._sse_client.flush_stream(self._stream_target)
        if self._end_stream:
            self._sse_client.end_stream(self._stream_target)
        try:
            stream = self._stream_target.streamer_session
        except AttributeError:
            stream = self._sse_client.sessions[self.session_id]
        self._streamed_in_session = stream["streamed"]
        self._sse_client.close_session(self._stream_target)
