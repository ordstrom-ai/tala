import copy
from contextlib import contextmanager
import time
import uuid

from tala.utils.func import setup_logger

logger = setup_logger(__name__)

RESULT_FIELDS = (
    "success",
    "name",
    "session_id",
    "start_time",
    "running_time",
    "avg_turn_time",
    "max_turn_time",
    "avg_stream_start",
    "max_stream_start",
    "avg_streaming_time",
    "max_streaming_time",
    "runs_executed",
)


class InteractionTestProgress:
    """Internal, synchronous observer; never owns or changes test execution."""
    def __init__(self, on_event):
        self._on_event = on_event
        self.callback_seconds = 0.0
        self._context = {}
        self._sequence = 0
        self._transcripts = []
        self._lines = []
        self._failure_description = None
        self._error_type = None

    def start_test(self, case, session_id, attempt_count):
        if self._on_event is None:
            return
        self._context = {
            "execution_id": str(uuid.uuid4()),
            "testcase_id": str(uuid.uuid4()),
            "name": case.get("name"),
            "session_id": session_id,
            "attempt_index": None,
            "attempt_count": attempt_count,
            "entry_index": None,
            "speaker": None,
        }
        self._sequence = 0
        self._transcripts = []
        self._lines = []
        self._failure_description = None
        self._error_type = None
        try:
            entry_count = len(case.get("interaction", []))
        except TypeError:
            entry_count = None
        self.emit("test_started", entry_count=entry_count)

    def start_attempt(self, attempt_index):
        self._context.update(attempt_index=attempt_index, entry_index=None, speaker=None)
        self._lines = []
        self._failure_description = None
        self._error_type = None
        self.emit("attempt_started")
        if self._transcripts:
            # The legacy result joins repetition transcripts with a newline.
            self.emit("transcript_delta", text="\n")

    def start_entry(self, entry_index, speaker):
        self._context.update(entry_index=entry_index, speaker=speaker)
        self.emit("entry_started")

    def complete_entry(self, success, elapsed_seconds, error=None):
        if error is not None:
            self.record_error(error)
        data = {"success": bool(success), "elapsed_seconds": elapsed_seconds, "status": self._status(success)}
        self._add_failure(data, success)
        self.emit("entry_completed", **data)
        self._context.update(entry_index=None, speaker=None)

    def fail(self, description):
        self._failure_description = description

    def record_error(self, error):
        self._error_type = type(error).__name__
        self.fail(f"Interaction execution raised {self._error_type}.")

    def transcript(self, output):
        if self._on_event is None:
            return
        text = output + "\n"
        self._lines.append(text)
        self.emit("transcript_delta", text=text)

    def system_output(self, response):
        if self._on_event is None:
            return
        try:
            output = response.get("output", {})
            data = {field: output[field] for field in ("moves", "utterance", "expected_passivity") if field in output}
        except (AttributeError, KeyError, TypeError):
            data = {}
        self.emit("system_output", **data)

    def complete_attempt(self, response=None, error=None):
        if self._on_event is None:
            return
        transcript = "".join(self._lines)
        self._transcripts.append(transcript)
        self._context.update(entry_index=None, speaker=None)
        self._complete("attempt_completed", response, transcript, error)

    def complete_test(self, response=None, error=None):
        if self._on_event is None:
            return
        self._context.update(attempt_index=None, entry_index=None, speaker=None)
        self._complete("test_completed", response, "\n".join(self._transcripts), error)

    def _complete(self, event, response, transcript, error):
        if error is not None:
            self.record_error(error)
        response = response if response is not None else {"success": False}
        result = {field: response[field] for field in RESULT_FIELDS if field in response}
        result["transcript"] = transcript
        self._add_failure(result, response["success"])
        data = {"status": self._status(response["success"]), "result": result, "raised": error is not None}
        if self._error_type is not None:
            data["error_type"] = self._error_type
        self.emit(event, **data)

    def _status(self, success):
        if self._error_type is not None:
            return "error"
        return "passed" if success else "failed"

    def _add_failure(self, data, success):
        if not success:
            data["failure_description"] = self._failure_description or "Interaction entry failed."
            if self._error_type is not None:
                data["error_type"] = self._error_type

    @contextmanager
    def request(self, request_type):
        if self._on_event is None:
            yield
            return
        self.emit("request_started", request_type=request_type)
        started = time.perf_counter()
        callback_seconds = self.callback_seconds
        try:
            yield
        except BaseException as error:
            # Observe even legacy BaseException subclasses, without swallowing
            # them or changing which exceptions the tester handles.
            self.emit(
                "request_completed",
                request_type=request_type,
                success=False,
                elapsed_seconds=self.elapsed_since(started, callback_seconds),
                error_type=type(error).__name__,
            )
            raise
        else:
            self.emit(
                "request_completed",
                request_type=request_type,
                success=True,
                elapsed_seconds=self.elapsed_since(started, callback_seconds),
            )

    def elapsed_since(self, started, callback_seconds):
        return max(0.0, time.perf_counter() - started - (self.callback_seconds - callback_seconds))

    def emit(self, event, **data):
        if self._on_event is None:
            return
        started = time.perf_counter()
        try:
            self._sequence += 1
            message = {
                "schema_version": 1,
                "event": event,
                **self._context,
                "sequence": self._sequence,
                "timestamp": time.time(),
                "data": data,
            }
            self._on_event(copy.deepcopy(message))
        except Exception as error:
            # Observer failures must not fail an interaction or expose payloads.
            logger.warning("interaction progress callback failed", error_type=type(error).__name__)
        finally:
            self.callback_seconds += time.perf_counter() - started
