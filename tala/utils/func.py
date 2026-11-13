import copy
import json
import logging
import os
import re
import sys
import uuid

from structlog.processors import JSONRenderer, TimeStamper, StackInfoRenderer, format_exc_info
from structlog.stdlib import add_log_level, filter_by_level, add_logger_name
import structlog

from tala.utils.log_context import correlation_context, request_id_from_payload


class EnvironmentVariableNotDefinedException(Exception):
    pass


def getenv(key, default=None):
    value = os.getenv(key, default)
    if value:
        return value
    if default is None:
        raise EnvironmentVariableNotDefinedException(
            f"Expected environment variable '{key}' to be defined but it wasn't"
        )


def setup_logger(name):
    logger = structlog.get_logger(name)
    try:
        log_level = os.getenv("LOG_LEVEL", default="INFO")
        configure_stdout_logging(log_level)
        return logger
    except Exception:
        logger.exception("exception during logger setup")
        raise


class FuncBase:
    def _setup_logger(self, request, logger, headers=None):
        header_context = correlation_context(headers)

        def get_session_id():
            try:
                return request["session"]["session_id"]
            except KeyError:
                return header_context.get("session_id", "unknown-session-id")

        def get_device_id():
            try:
                return request["session"]["device_id"]
            except KeyError:
                return "unknown-device-id"

        def get_request_id():
            request_id = request_id_from_payload(request)
            return header_context.get("request_id") if request_id is None else request_id

        session = _value_at(request, "session")
        context = dict(header_context)
        context.update({
            "session_id": get_session_id(),
            "device_id": get_device_id(),
        })
        request_id = get_request_id()
        optional_context = {
            "request_id": request_id,
            "correlation_id": header_context.get("correlation_id", request_id),
            "offer_id": _value_at(session, "offer_id"),
            "turn_id": _value_at(session, "turn_counter"),
        }
        context.update({field: value for field, value in optional_context.items() if value is not None})
        self.logger = logger.bind(**context)


def _value_at(value, key):
    try:
        return value[key]
    except (KeyError, TypeError):
        return None


REDACTED_LOG_FIELDS_IN_SESSION = [
    "asr_hints",
    "dme_http_services",
    "expected_input",
    "ndu",
    "nlg",
    "nlu",
    "odb",
    "tis",
    "tts",
    "visual_output",
]

MAX_LOG_RECORD_BYTES = 6 * 1024
PRIORITIZED_LOG_FIELDS = (
    "event", "level", "logger", "time", "timestamp", "request_id", "operation_Id", "operation_id", "trace_id",
    "span_id", "correlation_id", "session_id", "device_id", "offer_id", "turn_id", "utterance_id"
)
CORE_LOG_FIELDS = ("event", "level", "logger", "time", "timestamp")
SNAPSHOT_METADATA_FIELDS = (
    "log_snapshot_id", "log_snapshot_state", "log_snapshot_bytes", "log_fields_archived", "log_fields_unavailable",
    "log_snapshot_error", "log_snapshot_reason"
)
_LOG_SNAPSHOT_WRITER = None
_LOG_SNAPSHOT_POLICY = None
TRANSCRIPT_LOG_FIELDS = frozenset({
    "utterance",
    "user_utterance",
    "system_utterance",
    "original_utterance",
    "corrected_utterance",
    "latest_user_utterance",
    "latest_system_utterance",
    "provided_system_utterance",
    "gpt_system_utterance",
    "full_reply_content",
    "next_segment",
    "chunk",
    "streamed",
    "corrected_text",
    "hypotheses",
    "utterance_hypotheses",
    "corrections",
    "transcript",
    "messages",
})


def set_log_snapshot_writer(snapshot_writer):
    """Set the optional writer that stores oversized, already-redacted log events.

    The writer must implement ``write_snapshot(snapshot_id, snapshot_json)`` and return
    only after the snapshot is durably retrievable by its ID. Implementations should
    apply bounded timeouts and never include storage credentials in the returned log.
    A writer failure does not fail the application request; the emitted log reports
    ``failed`` and the payload is unavailable.
    Configuring a writer does not authorize capture: a separate admission policy
    is required, and recognized transcript content is never captured here.
    """
    global _LOG_SNAPSHOT_WRITER
    previous_writer = _LOG_SNAPSHOT_WRITER
    _LOG_SNAPSHOT_WRITER = snapshot_writer
    return previous_writer


def set_log_snapshot_policy(snapshot_policy):
    """Set explicit admission for approved, already-redacted diagnostic events.

    ``permits_snapshot(event)`` must return exactly True to allow a write. It
    receives a detached JSON representation and must reject unapproved content,
    secrets, and transcript data in application-specific schemas. Known transcript
    fields are rejected independently; this is not a general-purpose PII detector.
    No policy is installed by default. Application policy approval is separate
    from storage access, and a policy must not mutate an event to grant permission.
    """
    global _LOG_SNAPSHOT_POLICY
    previous_policy = _LOG_SNAPSHOT_POLICY
    _LOG_SNAPSHOT_POLICY = snapshot_policy
    return previous_policy


class BoundedJSONRenderer:
    """Compact oversized events only after archival, preserving unarchived content by default.

    Legacy fallback records can still exceed Azure's limits. Strictly bounded
    unavailable summaries require an explicit ``preserve_unarchived_fields=False``.
    """
    def __init__(
        self,
        max_bytes=MAX_LOG_RECORD_BYTES,
        snapshot_writer=None,
        preserve_unarchived_fields=True,
        snapshot_policy=None
    ):
        if max_bytes < 256:
            raise ValueError("The log record budget must be at least 256 bytes for snapshot metadata.")
        self.max_bytes = max_bytes
        self.snapshot_writer = snapshot_writer
        self.snapshot_policy = snapshot_policy
        self.preserve_unarchived_fields = preserve_unarchived_fields
        self._renderer = JSONRenderer(sort_keys=False)

    def __call__(self, logger, name, event_dict):
        ordered_event = self._prioritize_fields(event_dict)
        rendered = self._render(logger, name, ordered_event)
        if self._within_limit(rendered):
            return rendered

        snapshot_id = str(uuid.uuid4())
        snapshot_json = rendered
        snapshot_state = "not_configured"
        snapshot_error = None
        snapshot_reason = None
        policy_event, contains_transcript = self._inspect_snapshot(snapshot_json)
        snapshot_writer = self.snapshot_writer if self.snapshot_writer is not None else _LOG_SNAPSHOT_WRITER
        snapshot_policy = self.snapshot_policy if self.snapshot_policy is not None else _LOG_SNAPSHOT_POLICY
        if contains_transcript:
            snapshot_state = "not_permitted"
            snapshot_reason = "transcript_content_not_permitted"
        elif snapshot_writer is not None:
            snapshot_state = "not_permitted"
            snapshot_reason = "capture_policy_not_configured"
            permitted = False
            if snapshot_policy is not None:
                try:
                    permitted = snapshot_policy.permits_snapshot(policy_event) is True
                    snapshot_reason = None if permitted else "capture_policy_rejected"
                except Exception as error:
                    snapshot_reason = "capture_policy_failed"
                    snapshot_error = type(error).__name__
            if permitted:
                try:
                    snapshot_writer.write_snapshot(snapshot_id, snapshot_json)
                    snapshot_state = "stored"
                except Exception as error:
                    snapshot_state = "failed"
                    snapshot_error = type(error).__name__

        snapshot_metadata = self._snapshot_metadata(
            snapshot_id, snapshot_state, len(snapshot_json.encode("utf-8")), snapshot_error, snapshot_reason
        )
        if snapshot_state != "stored" and (self.preserve_unarchived_fields or contains_transcript):
            fallback = dict(ordered_event)
            fallback.update(snapshot_metadata)
            return self._render(logger, name, self._prioritize_fields(fallback))

        summary = self._snapshot_summary(
            logger,
            name,
            ordered_event,
            snapshot_metadata,
        )
        return self._render(logger, name, summary)

    @staticmethod
    def _inspect_snapshot(snapshot_json):
        contains_transcript = False

        def inspect_object(event):
            nonlocal contains_transcript
            # Check every JSON object, including nested requests and stream frames.
            if TRANSCRIPT_LOG_FIELDS.intersection(event):
                contains_transcript = True
            if event.get("event") == "STREAMING_CHUNK" and "data" in event:
                contains_transcript = True
            if event.get("event_type") in (
                "user_utterance", "user_utterance_received", "user_utterance_correction", "utterance_corrected",
                "system_utterance_fragment"
            ) and "text" in event:
                contains_transcript = True
            return event

        return json.loads(snapshot_json, object_hook=inspect_object), contains_transcript

    @staticmethod
    def _prioritize_fields(event_dict):
        ordered_event = {
            field: event_dict[field]
            for field in PRIORITIZED_LOG_FIELDS + SNAPSHOT_METADATA_FIELDS if field in event_dict
        }
        ordered_event.update({field: value for field, value in event_dict.items() if field not in ordered_event})
        return ordered_event

    def _render(self, logger, name, event_dict):
        return self._renderer(logger, name, event_dict)

    def _field_size(self, logger, name, field, value):
        return len(self._render(logger, name, {field: value}).encode("utf-8"))

    def _within_limit(self, rendered):
        return len(rendered.encode("utf-8")) <= self.max_bytes

    @staticmethod
    def _snapshot_metadata(snapshot_id, snapshot_state, snapshot_bytes, snapshot_error, snapshot_reason=None):
        metadata = {
            "log_snapshot_id": snapshot_id,
            "log_snapshot_state": snapshot_state,
            "log_snapshot_bytes": snapshot_bytes,
        }
        if snapshot_error:
            metadata["log_snapshot_error"] = snapshot_error
        if snapshot_reason:
            metadata["log_snapshot_reason"] = snapshot_reason
        return metadata

    def _snapshot_summary(self, logger, name, event_dict, snapshot_metadata):
        summary = dict(event_dict)
        summary.update(snapshot_metadata)
        snapshot_state = snapshot_metadata["log_snapshot_state"]
        count_field = "log_fields_archived" if snapshot_state == "stored" else "log_fields_unavailable"
        summary[count_field] = 0

        optional_fields = [
            field for field in event_dict
            if field not in PRIORITIZED_LOG_FIELDS and field not in SNAPSHOT_METADATA_FIELDS
        ]
        context_fields = [
            field for field in event_dict if field in PRIORITIZED_LOG_FIELDS and field not in CORE_LOG_FIELDS
        ]
        core_fields = [field for field in CORE_LOG_FIELDS if field in event_dict]
        for field_group in (optional_fields, context_fields, core_fields):
            field_sizes = {field: self._field_size(logger, name, field, event_dict[field]) for field in field_group}
            for field in sorted(field_group, key=field_sizes.get, reverse=True):
                rendered = self._render(logger, name, self._prioritize_fields(summary))
                if self._within_limit(rendered):
                    return self._prioritize_fields(summary)
                marker = self._snapshot_field_marker(field_sizes[field], snapshot_state)
                if self._field_size(logger, name, field, marker) < field_sizes[field]:
                    summary[field] = marker
                else:
                    del summary[field]
                summary[count_field] += 1

        summary = self._prioritize_fields(summary)
        if self._within_limit(self._render(logger, name, summary)):
            return summary
        minimal_summary = {
            "event": "oversized log event",
            "log_snapshot_id": snapshot_metadata["log_snapshot_id"],
            "log_snapshot_state": snapshot_state,
            "log_snapshot_bytes": snapshot_metadata["log_snapshot_bytes"],
        }
        return minimal_summary

    @staticmethod
    def _snapshot_field_marker(original_bytes, snapshot_state):
        if snapshot_state == "stored":
            return {"in_snapshot": True, "original_bytes": original_bytes}
        return {"unavailable": True, "reason": f"snapshot_{snapshot_state}", "original_bytes": original_bytes}


def log_models(original_body, logger, models=REDACTED_LOG_FIELDS_IN_SESSION):
    log_body = copy.deepcopy(original_body)
    if "tis" in log_body.get("session", {}):
        del log_body["session"]["tis"]
    for field in models:
        if field in log_body.get("session", {}):
            logger.info(f"Model log for {field}", body=log_body["session"][field])


def redact_bulky_entries_in_session(_, __, input_event_dict):
    if "session" in input_event_dict.get("body", {}):
        event_dict = copy.deepcopy(input_event_dict)
        for field in REDACTED_LOG_FIELDS_IN_SESSION:
            if field in event_dict.get("body", {}).get("session", {}):
                event_dict["body"]["session"][field] = "[REDACTED]"
        return event_dict
    return input_event_dict


def configure_stdout_logging(level=None):
    level = level or os.getenv("LOG_LEVEL", default="INFO")
    log_file = os.getenv("TDM_LOG_FILE")
    structlog.configure(
        processors=[
            filter_by_level,
            redact_bulky_entries_in_session,
            add_log_level,
            add_logger_name,
            TimeStamper(fmt="iso", key="time"),
            StackInfoRenderer(),
            format_exc_info,
            BoundedJSONRenderer(preserve_unarchived_fields=True),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if not root_logger.handlers and not _uses_azure_functions_worker():
        root_logger.addHandler(_create_stdout_handler())
    if log_file and not _has_file_handler(root_logger, log_file):
        file_handler = logging.FileHandler(log_file, mode="a")
        file_handler.setFormatter(_plain_formatter())
        root_logger.addHandler(file_handler)

    _configure_access_logging(level)


def _configure_access_logging(level):
    access_logger = logging.getLogger("gunicorn.access")
    access_logger.setLevel(level)
    if access_logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=[
                add_log_level,
                add_logger_name,
                TimeStamper(fmt="iso", key="time"),
                StackInfoRenderer(),
                format_exc_info,
                combined_logformat,
            ],
        )
    )
    access_logger.addHandler(handler)
    access_logger.propagate = False


def _create_stdout_handler():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_plain_formatter())
    return handler


def _plain_formatter():
    return structlog.stdlib.ProcessorFormatter(processor=structlog.dev.ConsoleRenderer(colors=False))


def _has_file_handler(logger, filename):
    expected_filename = os.path.abspath(filename)
    for handler in logger.handlers:
        try:
            if os.path.abspath(handler.baseFilename) == expected_filename:
                return True
        except AttributeError:
            continue
    return False


def _uses_azure_functions_worker():
    return os.getenv("FUNCTIONS_WORKER_RUNTIME", "").lower() == "python"


def combined_logformat(logger, name, event_dict):
    if event_dict.get('logger') == "gunicorn.access":
        message = event_dict['event']

        parts = [
            r'(?P<host>\S+)',  # host %h
            r'\S+',  # indent %l (unused)
            r'(?P<user>\S+)',  # user %u
            r'\[(?P<time>.+)\]',  # time %t
            r'"(?P<request>.+)"',  # request "%r"
            r'(?P<status>[0-9]+)',  # status %>s
            r'(?P<size>\S+)',  # size %b (careful, can be '-')
            r'"(?P<referer>.*)"',  # referer "%{Referer}i"
            r'"(?P<agent>.*)"',  # user agent "%{User-agent}i"
        ]
        pattern = re.compile(r'\s+'.join(parts) + r'\s*\Z')
        m = pattern.match(message)
        result = m.groupdict()

        if result["user"] == "-":
            result["user"] = None

        result["status"] = int(result["status"])

        if result["size"] == "-":
            result["size"] = 0
        else:
            result["size"] = int(result["size"])

        if result["referer"] == "-":
            result["referer"] = None

        event_dict.update(result)
        event_dict["event"] = "endpoint accessed"

    return event_dict
