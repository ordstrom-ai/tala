import copy
import uuid
import re
import json
from itertools import tee
import warnings
import requests
import time
import traceback

import structlog

from tala.model.interpretation import Interpretation
from tala.model.input_hypothesis import InputHypothesis
from tala.model.common import Modality
from tala.model.user_move import UserMove, DDDSpecificUserMove
from tala.utils.tdm_client import TDMClient

from tala.testing.interaction.comparison import StringComparison, MoveComparison
from tala.testing.interaction.progress import InteractionTestProgress
from tala.testing.interaction.stream_listener import StreamListener
from tala.testing.interaction.stream_listener import StreamListenerError
from tala.testing.interaction.stream_listener import StreamListenerTimeoutError

from tala.utils.func import configure_stdout_logging, getenv

SPEAKER = "speaker"
USER = "user"
SYSTEM = "system"
TEST_NAME = "name"
MOVE_CONTENT = "move_content"
INTERPRETATIONS = "interpretations"
SPEECH_CONTENT = "speech_content"
OUTPUT = "output"
MOVES = "moves"
SESSION = "session"
EXPECTED_PASSIVITY = "expected_passivity"
UTTERANCE = "utterance"
REPEAT = "repeat"
REQUIRE_OUTCOMES = "require_outcomes"
REQUIRE_OUTCOME_ENTRY_INDEX = "entry_index"
REQUIRE_OUTCOME_MOVES = "moves"

TDM_PROTOCOL_VERSION = "3.4"

DEFAULT_DEVICE_ID = "interaction-tester"

NO_VOICE_ACTIVATION = {"no_content": {}}

logger = structlog.get_logger(__name__)
log_level = getenv("LOG_LEVEL", "INFO")
configure_stdout_logging(log_level)
REQUEST_TIMEOUT_SECONDS = getenv("TDM_REQUEST_TIMEOUT_SECONDS", "120")

REDACTED_LOG_FIELDS = {
    "ndu",
    "nlg",
    "odb",
    "tts",
    "nlu",
    "tis",
    "encrypted_data",
    "asr_hints",
    "visual_output",
    "expected_input",
    "dme_http_services",
}


def _redact_interaction_log_payload(payload):
    try:
        redacted_payload = copy.deepcopy(payload)
        for key in ("context", "session", "output"):
            try:
                section = redacted_payload.get(key)
            except AttributeError:
                continue
            for field in REDACTED_LOG_FIELDS:
                try:
                    if field in section:
                        section[field] = "[REDACTED]"
                except TypeError:
                    break
        return redacted_payload
    except Exception:
        return payload


class InteractionTesterException(BaseException):
    pass


class NoInputAcceptedException(InteractionTesterException):
    pass


class QueryException(BaseException):
    pass


class ZeroDivisionWarning(UserWarning):
    pass


class OutputBuffer:
    def __init__(self):
        self._content_lines = []

    def add(self, new_content):
        self._content_lines.append(new_content)

    def __str__(self):
        output = ""
        for line in self._content_lines:
            output += line + "\n"
        return output


class InteractionTester:
    def __init__(self, port, device_id=DEFAULT_DEVICE_ID, use_streaming=False, on_event=None):
        self._session_id = f"interaction-tester-session-{str(uuid.uuid4())}"
        self._device_id = device_id
        self._port = port
        self._use_streaming = use_streaming
        self._progress = InteractionTestProgress(on_event)

    def start_session(self, offer=None):
        self._initialize_session_object()
        if offer:
            self._session_data.update(offer)
        self._session_data["neural"] = self._neural
        with self._progress.request("start_session"):
            self._latest_response = self._client.start_session(self._session_data)
        logger.info("starting session", session_id=self._session_id)
        self._session_data = self._latest_response[SESSION]

    def _initialize_session_object(self):
        self._session_data = {"device_id": self._device_id, "session_id": self._session_id}

    def run_testcase(self, case, offer=None):
        repeat, required_outcomes = self._get_repeat_and_required_outcomes(case)
        self._progress.start_test(case, self._session_id, repeat)
        try:
            if repeat == 1 and not required_outcomes:
                response = self._run_testcase_once(case, offer)
            else:
                response = self._run_testcase_with_repeats(case, offer, repeat, required_outcomes)
        except BaseException as error:
            self._progress.complete_test(error=error)
            raise
        self._progress.complete_test(response)
        return response

    def _run_testcase_once(self, case, offer=None, run_index=None, run_count=None):
        self._progress.start_attempt(run_index if run_index is not None else 1)
        try:
            response = self._execute_testcase_once(case, offer, run_index, run_count)
        except BaseException as error:
            self._progress.complete_attempt(error=error)
            raise
        self._progress.complete_attempt(response)
        return response

    def _execute_testcase_once(self, case, offer=None, run_index=None, run_count=None):
        self._initialize_testcase(case, run_index=run_index, run_count=run_count)
        self._start_clock()
        self.start_session(offer)
        success = True
        self._previous_entry_type = None
        interaction_entries, following_entries = tee(case["interaction"])
        following_entries = iter(following_entries)
        next(following_entries, None)
        try:
            for entry_index, entry in enumerate(interaction_entries):
                self._current_entry_index = entry_index
                self._next_interaction_entry = next(following_entries, None)
                success = self._run_entry(entry, success)
                if not success:
                    self._stop_clock()
                    return self._create_response(self._result)
                self._previous_entry_type = entry[SPEAKER]
        except InteractionTesterException as e:
            self._progress.record_error(e)
            self._buffer_output('!!!! Exception raised during test !!!!')
            self._buffer_output(f"Exception: {e}", progress_output=f"Exception: {type(e).__name__}")
            self._result = {"success": False, "failure_description": str(e)}
        except Exception as e:
            self._progress.record_error(e)
            self._buffer_output('!!!! General exception raised during test !!!!')
            self._buffer_output(f"Exception: {e}", progress_output=f"Exception: {type(e).__name__}")
            self._result = {"success": False, "failure_description": str(e)}
        else:
            self._buffer_output('=== End interaction test ===')
            self._result = {"success": True}
        self._stop_clock()
        return self._create_response(self._result)

    def _run_entry(self, entry, success):
        self._progress.start_entry(self._current_entry_index, entry[SPEAKER])
        started = time.perf_counter()
        callback_seconds = self._progress.callback_seconds
        try:
            if entry[SPEAKER] == USER:
                success = self._do_user_turn(entry)
            elif entry[SPEAKER] == SYSTEM:
                success = self._do_system_turn(entry)
        except BaseException as error:
            self._progress.complete_entry(False, self._progress.elapsed_since(started, callback_seconds), error)
            raise
        self._progress.complete_entry(success, self._progress.elapsed_since(started, callback_seconds))
        return success

    def _initialize_testcase(self, testcase, run_index=None, run_count=None):
        self._output_buffer = OutputBuffer()
        self._ddd_name = testcase["target_ddd"]
        self._neural = testcase.get("neural")
        self._start_date = {time.asctime()}
        url = self._patch_url_with_port(testcase["url"])
        self._client = TDMClient(url)
        self._test_name = testcase["name"]
        self._system_moves_seen = []
        self._current_entry_index = None
        run_label = ""
        if run_index is not None and run_count is not None:
            run_label = f" (run {run_index}/{run_count})"
        self._buffer_output(f'\n=== Begin interaction test "{self._test_name}"{run_label} ===')
        self._request_times = []
        self._stream_start_times = []
        self._stream_end_times = []
        self._silent_stream_skip_count = 0

    def _start_stream_listener(self):
        if self._use_streaming:
            self._stream_listener_thread = StreamListener(
                StreamListener.SSE_BROKER_ENDPOINT_HTTPS, self._session_id, logger
            )
            self._stream_listener_thread.start()
            try:
                self._stream_listener_thread.wait_until_started()
            except (StreamListenerError, StreamListenerTimeoutError):
                self._stop_stream_listener()
                raise

    def _stop_stream_listener(self):
        listener = getattr(self, "_stream_listener_thread", None)
        if listener is not None:
            self._stream_listener_thread = None
            listener.stop()

    def _start_clock(self):
        self._start_time = time.time()
        self._clock_callback_seconds = self._progress.callback_seconds
        self._turn_times = []

    def _patch_url_with_port(self, url):
        if self._port:
            new_url = re.sub(r"^(https?:[^:]*):\d+/(.+)", rf"\1:{self._port}/\2", url)
            return new_url
        return url

    def _buffer_output(self, output, progress_output=None):
        logger.info("interaction test output", output=output)
        self._output_buffer.add(output)
        self._progress.transcript(output if progress_output is None else progress_output)

    def _print_buffer(self):
        print(str(self._output_buffer))

    def check_for_consecutive_speaker(self, speaker):
        if self._previous_entry_type == speaker:
            raise InteractionTesterException(f"Two consecutive entries define '{speaker}' input")

    def _do_user_turn(self, user_entry):
        def create_interpretation(moves, utterance_content=""):
            return Interpretation([self._create_user_move(move) for move in moves], Modality.OTHER, utterance_content)

        def create_interpretations_from_dicts(dict_list, utterance):
            interpretations = []
            for entry in dict_list:
                interpretations.append(
                    Interpretation([create_user_move(move) for move in entry["moves"]], entry["modality"], utterance)
                )
            return interpretations

        def create_user_move(move_dict):
            return DDDSpecificUserMove(
                move_dict["ddd"], move_dict["semantic_expression"], move_dict["perception_confidence"],
                move_dict["understanding_confidence"]
            )

        def interpretations_as_json(interpretations):
            return json.dumps([interpretation.as_json() for interpretation in interpretations])

        self.check_for_consecutive_speaker(USER)

        start_time = time.time()
        callback_seconds = self._progress.callback_seconds

        if MOVE_CONTENT in user_entry:
            moves = user_entry[MOVE_CONTENT]
            self._buffer_output(f"U> {json.dumps(moves)}")
            utterance = user_entry.get("utterance", "")
            interpretation = create_interpretation(moves, utterance)
            self._request_semantic_input([interpretation])
        elif INTERPRETATIONS in user_entry:
            utterance = user_entry.get("utterance", "")
            interpretations = create_interpretations_from_dicts(user_entry[INTERPRETATIONS], utterance)
            entities = user_entry.get("entities", [])
            self._buffer_output(f"U> {utterance if utterance else interpretations_as_json(interpretations)}")
            self._request_semantic_input(interpretations, entities=entities)
        elif EXPECTED_PASSIVITY in user_entry:
            expected_passivity = user_entry[EXPECTED_PASSIVITY]
            self._buffer_output(f"U> {{expected_passivity={expected_passivity}}}")
            if self._passivity_mismatch(user_entry[EXPECTED_PASSIVITY]):
                self._create_passivity_mismatch_description(user_entry[EXPECTED_PASSIVITY])
                return False
            self._request_passivity()
        elif SPEECH_CONTENT in user_entry:
            utterance = user_entry.get(SPEECH_CONTENT)
            self._buffer_output(f"U> {utterance}")
            self._request_speech_input(utterance)
        else:
            raise InteractionTesterException("Nothing to do in user entry:", user_entry)
        end_time = time.time()
        self._turn_times.append(end_time - start_time - (self._progress.callback_seconds - callback_seconds))
        return True

    def _request_semantic_input(self, interpretations, entities=None):
        with self._progress.request("semantic_input"):
            self._start_stream_listener()
            self._request_times.append(time.time())
            try:
                self._latest_response = self._client.request_semantic_input(
                    interpretations, self._session_data, entities
                )
            except Exception as e:
                self._stop_stream_listener()
                raise InteractionTesterException("Exception when executing test", e, traceback.format_exc())
            logger.info("semantic_input response", response=_redact_interaction_log_payload(self._latest_response))
            self._add_streamed_output()
            self._update_session_data()

    def _add_streamed_output(self):
        if not self._use_streaming:
            return

        try:
            output = self._latest_response[OUTPUT]
        except KeyError as e:
            warnings.warn(f"latest response has no '{OUTPUT}' field: {e}")
            self._stream_start_times.append(None)
            self._stream_end_times.append(None)
            self._stop_stream_listener()
            return

        http_utterance = output.get(UTTERANCE)
        if (http_utterance is None or http_utterance == "") and not self._next_system_entry_expects_speech():
            self._silent_stream_skip_count += 1
            self._stream_start_times.append(None)
            self._stream_end_times.append(None)
            self._stop_stream_listener()
            return

        try:
            output[UTTERANCE] = self._stream_listener_thread.system_utterance
            self._stream_start_times.append(self._stream_listener_thread.streaming_started)
            self._stream_end_times.append(self._stream_listener_thread.streaming_ended)
        except KeyError as e:
            warnings.warn(f"latest response has no '{OUTPUT}' field: {e}")
        finally:
            self._stop_stream_listener()

    def _next_system_entry_expects_speech(self):
        system_entry = self._next_interaction_entry
        if system_entry is None:
            return True
        if system_entry.get(SPEAKER) != SYSTEM:
            return True
        return SPEECH_CONTENT in system_entry

    def _request_passivity(self):
        with self._progress.request("passivity"):
            self._start_stream_listener()
            self._request_times.append(time.time())
            try:
                self._latest_response = self._client.request_passivity(self._session_data)
            except Exception as e:
                self._stop_stream_listener()
                raise InteractionTesterException("Exception when executing test", e, traceback.format_exc())
            logger.info("passivity response", response=_redact_interaction_log_payload(self._latest_response))
            self._add_streamed_output()
            self._update_session_data()

    def _request_speech_input(self, utterance):
        hypotheses = [InputHypothesis(utterance, 1.0)]
        with self._progress.request("speech_input"):
            self._start_stream_listener()
            self._request_times.append(time.time())
            try:
                self._latest_response = self._client.request_speech_input(hypotheses, self._session_data)
            except Exception as e:
                self._stop_stream_listener()
                raise InteractionTesterException("Exception when executing test", e, traceback.format_exc())
            logger.info("speech_input response", response=_redact_interaction_log_payload(self._latest_response))
            self._add_streamed_output()
            self._update_session_data()

    def _update_session_data(self):
        try:
            self._session_data = self._latest_response["session"]
        except KeyError:
            warnings.warn(f"response has no session data: {self._latest_response}")

    def _create_user_move(self, move):
        prefixed = self._split_prefixed_move(move)
        if prefixed:
            ddd, semantic_expression = prefixed
            return DDDSpecificUserMove(ddd, semantic_expression, 1.0, 1.0)
        if self._ddd_name:
            return DDDSpecificUserMove(self._ddd_name, move, 1.0, 1.0)
        return UserMove(move, 1.0, 1.0)

    def _split_prefixed_move(self, move):
        if not isinstance(move, str):
            return None
        if ":" not in move:
            return None
        ddd, remainder = move.split(":", 1)
        if not ddd or not remainder:
            return None
        if remainder.startswith(("ask(", "answer(", "request(", "report(", "icm:")):
            return ddd, remainder
        return None

    def _do_system_turn(self, system_entry):
        self.check_for_consecutive_speaker(SYSTEM)
        while self._is_request_for_service_invocation():
            self._make_service_request_and_create_tdm_request_with_service_invocation_result()
        else:

            self._progress.system_output(self._latest_response)
            if self._latest_response == NO_VOICE_ACTIVATION:
                return self._create_no_voice_activation_response()

            if EXPECTED_PASSIVITY in system_entry and self._passivity_mismatch(system_entry[EXPECTED_PASSIVITY]):
                return self._create_passivity_mismatch_description(system_entry[EXPECTED_PASSIVITY])
            if MOVE_CONTENT in system_entry:
                if SPEECH_CONTENT in system_entry:
                    return (
                        self._assert_system_moves_are_matched_by(system_entry[MOVE_CONTENT])
                        and self._assert_system_utterance_is_matched_by(system_entry[SPEECH_CONTENT])
                    )
                return self._assert_system_moves_are_matched_by(system_entry[MOVE_CONTENT])
            if SPEECH_CONTENT in system_entry:
                return self._assert_system_utterance_is_matched_by(system_entry[SPEECH_CONTENT])

    def _is_request_for_service_invocation(self):
        if self._is_request_for_service_query_invocation():
            return True
        elif self._is_request_for_service_validation_invocation():
            return True
        elif self._is_request_for_service_action_invocation():
            return True

    def _is_request_for_service_query_invocation(self):
        if "predicate" in self._latest_response:
            return True

    def _is_request_for_service_validation_invocation(self):
        if "validator_name" in self._latest_response:
            return True

    def _is_request_for_service_action_invocation(self):
        if "action_name" in self._latest_response:
            return True

    def _make_service_request_and_create_tdm_request_with_service_invocation_result(self):
        if self._is_request_for_service_query_invocation():
            self._make_service_request_and_create_tdm_request_with_service_query_invocation_result()
        elif self._is_request_for_service_validation_invocation():
            self._make_service_request_and_create_tdm_request_with_service_validator_invocation_result()
        elif self._is_request_for_service_action_invocation():
            self._make_service_request_and_create_tdm_request_with_service_action_invocation_result()

    def _make_service_request_and_create_tdm_request_with_service_query_invocation_result(self):
        predicate = self._latest_response["predicate"]
        url = self._latest_response["url"]
        parameters = self._latest_response["parameters"]
        session = self._latest_response["session"]
        min_results = self._latest_response["min_results"]
        max_results = self._latest_response["max_results"]

        logger.info("invoking service query", predicate=predicate, parameters=parameters)
        query_results = self._make_query_to_http_service(predicate, url, parameters, min_results, max_results, session)
        if query_results["status"] != "success":
            raise QueryException(
                f"HTTP service query failed: url: {url}, parameters:{parameters}, result: {query_results}"
            )

        logger.info("requesting dme with", results=query_results)
        self._make_results_request_for_dme(
            "query_results", {
                "predicate": predicate,
                "url": url,
                "parameters": parameters,
                "ddd_name": self._latest_response["ddd_name"],
                "results": query_results["data"]["result"],
                "earlier_results": self._latest_response["earlier_results"]
            }
        )

    def _make_results_request_for_dme(self, type_, results):
        request = {
            "version": TDM_PROTOCOL_VERSION,
            "request": self._latest_response["original_request"],
            "session": self._latest_response["session"]
        }
        request["request"][type_] = results
        with self._progress.request(type_):
            self._latest_response = self._client.make_request(request)
        self._update_session_data()
        logger.info("results request response", response=_redact_interaction_log_payload(self._latest_response))

    def _make_query_to_http_service(self, name, url, parameters, min_results, max_results, session):
        data = {
            "session": session,
            "min_results": min_results,
            "max_results": max_results,
            "request": {
                "type": "query",
                "name": name,
                "parameters": parameters,
            }
        }
        logger.info("making query request to http service", url=url, data=data)
        with self._progress.request("service_query"):
            response = requests.post(
                url,
                data=json.dumps(data),
                headers={"Content-type": "application/json"},
                timeout=self._request_timeout_seconds(),
            )
            try:
                response_dict = json.loads(response.text)
            except BaseException:
                logger.exception("Exception when loading response from service")
                raise QueryException(
                    f"Response to service request is not JSON: request_data='{data}', response='{response.text}'"
                )
        logger.info("query response from http service:", response_dict)
        return response_dict

    def _make_service_request_and_create_tdm_request_with_service_validator_invocation_result(self):
        validator_name = self._latest_response["validator_name"]
        url = self._latest_response["url"]
        parameters = self._latest_response["parameters"]
        session = self._latest_response["session"]

        logger.info("invoking service validator", validator=validator_name, parameters=parameters)
        query_results = self._validate_in_http_service(validator_name, url, parameters, session)
        self._make_results_request_for_dme(
            "validation_results", {
                "validator_name": validator_name,
                "url": url,
                "parameters": parameters,
                "ddd_name": self._latest_response["ddd_name"],
                "result": query_results,
                "earlier_results": self._latest_response["earlier_results"]
            }
        )

    def _validate_in_http_service(self, name, url, parameters, session):
        data = {
            "session": session,
            "request": {
                "type": "validator",
                "name": name,
                "parameters": parameters,
            }
        }
        with self._progress.request("service_validation"):
            response = requests.post(
                url,
                data=json.dumps(data),
                headers={"Content-type": "application/json"},
                timeout=self._request_timeout_seconds(),
            )
            response_dict = json.loads(response.text)
        return response_dict

    def _make_service_request_and_create_tdm_request_with_service_action_invocation_result(self):
        action_name = self._latest_response["action_name"]
        url = self._latest_response["url"]
        parameters = self._latest_response["parameters"]
        session = self._latest_response["session"]

        logger.info("invoking service request", action=action_name, parameters=parameters)
        action_result = self._perform_action_in_http_service(action_name, url, parameters, session)
        self._make_results_request_for_dme(
            "action_results", {
                "action_name": action_name,
                "url": url,
                "parameters": parameters,
                "ddd_name": self._latest_response["ddd_name"],
                "result": action_result,
                "earlier_results": self._latest_response["earlier_results"]
            }
        )

    def _perform_action_in_http_service(self, name, url, parameters, session):
        data = {
            "session": session,
            "request": {
                "type": "action",
                "name": name,
                "parameters": parameters,
            }
        }
        with self._progress.request("service_action"):
            response = requests.post(
                url,
                data=json.dumps(data),
                headers={"Content-type": "application/json"},
                timeout=self._request_timeout_seconds(),
            )
            response_dict = json.loads(response.text)
        return response_dict

    def _request_timeout_seconds(self):
        try:
            return float(REQUEST_TIMEOUT_SECONDS)
        except ValueError:
            return 120.0

    def _passivity_mismatch(self, expected_passivity_value):
        actual_value = self._latest_response[OUTPUT].get(EXPECTED_PASSIVITY)
        if not actual_value and actual_value != 0.0:
            return True
        if expected_passivity_value is True:
            return False
        if expected_passivity_value == actual_value:
            return False
        return True

    def _create_no_voice_activation_response(self):
        self._result = {
            "success": False,
            "failure_description": "Backend requires voice activation to process content."
        }
        self._progress.fail(self._result["failure_description"])
        self._buffer_output("S> <Backend requires voice activation to process content>")
        return False

    def _create_passivity_mismatch_description(self, expected_passivity_value):
        actual_value = self._latest_response[OUTPUT].get(EXPECTED_PASSIVITY, False)
        if actual_value is None:
            if expected_passivity_value is True:
                self._result = {
                    "success": False,
                    "failure_description": "Expected an expected_passivity, but none was set."
                }
            else:
                self._result = {
                    "success": False,
                    "failure_description": f"Expected expected_passivity={expected_passivity_value}, " +
                    "but no expected_passivity was set."
                }
        else:
            self._result = {
                "success": False,
                "failure_description": f"Expected expected_passivity={expected_passivity_value}, " +
                f"but actual expected_passivity was {actual_value}."
            }
        self._progress.fail(self._result["failure_description"])

    def _assert_system_moves_are_matched_by(self, expected_move_content):
        assert OUTPUT in self._latest_response, f"No {OUTPUT} in {self._latest_response}"
        actual_move_content = self._latest_response[OUTPUT].get(MOVES)
        if actual_move_content is None:
            self._result = {
                "success": False,
                "failure_description": f"No moves in output: {self._latest_response[OUTPUT]}"
            }
            self._progress.fail("No moves in output.")
            self._buffer_output(self._result["failure_description"], progress_output="No moves in output.")
            return False
        self._record_system_moves_seen(actual_move_content)
        try:
            is_alternatives = expected_move_content and all(hasattr(entry, "append") for entry in expected_move_content)
        except TypeError:
            is_alternatives = False
        if is_alternatives:
            comparison = None
            match = False
            for alternative in expected_move_content:
                comparison = MoveComparison(actual_move_content, alternative)
                if comparison.match():
                    match = True
                    break
            if not match:
                mismatch_description = comparison.mismatch_description() if comparison else (
                    f"expected: {json.dumps(expected_move_content)}\n"
                    f"but got:  {json.dumps(actual_move_content)}"
                )
                self._result = {"success": False, "failure_description": mismatch_description}
                self._progress.fail(mismatch_description)
                self._buffer_output(mismatch_description)
                return False
        else:
            comparison = MoveComparison(actual_move_content, expected_move_content)
            if not comparison.match():
                self._result = {"success": False, "failure_description": comparison.mismatch_description()}
                self._progress.fail(self._result["failure_description"])
                self._buffer_output(comparison.mismatch_description())
                return False
        if self._turn_times:
            self._buffer_output(f"S> {json.dumps(actual_move_content)}: {self._turn_times[-1]:.2f} s")
        else:
            self._buffer_output(f"S> {json.dumps(actual_move_content)}")
        return True

    def _assert_system_utterance_is_matched_by(self, expected_speech_content):
        assert OUTPUT in self._latest_response, f"No {OUTPUT} in {self._latest_response}"
        actual_utterance_content = self._latest_response[OUTPUT].get(UTTERANCE)
        if actual_utterance_content is None:
            self._result = {
                "success": False,
                "failure_description": f"No utterance in output: {self._latest_response[OUTPUT]}"
            }
            self._progress.fail("No utterance in output.")
            self._buffer_output(self._result["failure_description"], progress_output="No utterance in output.")
            return False

        comparison = StringComparison(actual_utterance_content, expected_speech_content)
        if not comparison.match():
            self._result = {"success": False, "failure_description": comparison.mismatch_description()}
            self._progress.fail(self._result["failure_description"])
            self._buffer_output(comparison.mismatch_description())
            return False
        if self._turn_times:
            self._buffer_output(f"S> {actual_utterance_content}: {self._turn_times[-1]:.2f} s")
        else:
            self._buffer_output(f"S> {actual_utterance_content}")
        return True

    def _create_response(self, response):
        def get_stream_onset_times():
            onsets = []
            for request_sent, first_token in zip(self._request_times, self._stream_start_times):
                try:
                    onsets.append(first_token - request_sent)
                except TypeError:
                    pass
            return onsets

        def get_streaming_times():
            streaming_times = []
            for first_token, end_stream in zip(self._stream_start_times, self._stream_end_times):
                try:
                    streaming_times.append(end_stream - first_token)
                except TypeError:
                    pass
            return streaming_times

        onset_times = get_stream_onset_times()
        streaming_times = get_streaming_times()

        response["name"] = self._test_name
        response["session_id"] = self._session_id

        response["transcript"] = str(self._output_buffer)

        response["start_time"] = self._start_time
        response["running_time"] = self._end_time - self._start_time

        if self._use_streaming:
            try:
                response["avg_stream_start"] = sum(onset_times) / len(onset_times)
            except ZeroDivisionError:
                response["avg_stream_start"] = -1
                if self._silent_stream_skip_count < len(self._request_times):
                    warnings.warn(
                        "Attempted division by zero when calculating average stream start.\n"
                        "\tresponse[\"avg_stream_start\"] = sum(onset_times) / len(onset_times)\n"
                        f"\tonset_times = {onset_times}"
                        f"\trequest_times = {self._request_times}"
                        f"\tstream_start_times = {self._stream_start_times}", ZeroDivisionWarning
                    )

            response["max_stream_start"] = max(onset_times) if onset_times else -1

            try:
                response["avg_streaming_time"] = sum(streaming_times) / len(streaming_times)
            except ZeroDivisionError:
                response["avg_streaming_time"] = -1
                if self._silent_stream_skip_count < len(self._request_times):
                    warnings.warn(
                        "Attempted division by zero when calculating average stream time.\n"
                        "\tresponse[\"avg_streaming_time\"] = sum(streaming_times) / len(streaming_times)\n"
                        f"\tstreaming_times = {streaming_times}"
                        f"\tstream_start_times = {self._stream_start_times}"
                        f"\tstream_end_times = {self._stream_end_times}", ZeroDivisionWarning
                    )
            response["max_streaming_time"] = max(streaming_times) if streaming_times else -1

        response["avg_turn_time"] = sum(self._turn_times) / len(self._turn_times) if self._turn_times else 0
        response["max_turn_time"] = max(self._turn_times) if self._turn_times else 0

        return response

    def _run_testcase_with_repeats(self, case, offer, repeat, required_outcomes):
        outcomes_seen = [False] * len(required_outcomes)
        transcripts = []
        last_response = None
        runs_executed = 0
        for run_index in range(1, repeat + 1):
            runs_executed += 1
            response = self._run_testcase_once(case, offer, run_index=run_index, run_count=repeat)
            last_response = response
            transcripts.append(response["transcript"])
            if not response["success"]:
                return self._with_run_metadata(response, transcripts, runs_executed)
            self._record_required_outcomes_seen(outcomes_seen, required_outcomes, self._system_moves_seen)
            if required_outcomes and all(outcomes_seen):
                break

        if required_outcomes and not all(outcomes_seen):
            return self._missing_required_outcomes_response(
                required_outcomes, outcomes_seen, transcripts, runs_executed
            )

        if last_response is None:
            return self._run_testcase_once(case, offer)
        return self._with_run_metadata(last_response, transcripts, runs_executed)

    def _get_repeat_and_required_outcomes(self, testcase):
        repeat = testcase.get(REPEAT, 1)
        try:
            repeat = int(repeat)
        except (TypeError, ValueError):
            repeat = 1
        if repeat < 1:
            repeat = 1
        required_outcomes = self._normalize_required_outcomes(testcase.get(REQUIRE_OUTCOMES, []))
        return repeat, required_outcomes

    def _normalize_required_outcomes(self, required_outcomes):
        normalized = []
        for outcome in required_outcomes:
            if isinstance(outcome, dict):
                moves = outcome.get(REQUIRE_OUTCOME_MOVES)
                entry_index = outcome.get(REQUIRE_OUTCOME_ENTRY_INDEX)
            else:
                moves = outcome
                entry_index = None
            if moves is None:
                continue
            normalized.append(self._create_required_outcome(moves, entry_index))
        return normalized

    def _record_required_outcomes_seen(self, outcomes_seen, required_outcomes, system_moves):
        for index, outcome in enumerate(required_outcomes):
            if outcomes_seen[index]:
                continue
            if self._required_outcome_seen(system_moves, outcome):
                outcomes_seen[index] = True

    def _required_outcome_seen(self, system_moves, outcome):
        entry_index = outcome[REQUIRE_OUTCOME_ENTRY_INDEX]
        expected_moves = outcome[REQUIRE_OUTCOME_MOVES]
        for move_entry in system_moves:
            if entry_index is not None and move_entry[REQUIRE_OUTCOME_ENTRY_INDEX] != entry_index:
                continue
            comparison = MoveComparison(move_entry[REQUIRE_OUTCOME_MOVES], expected_moves)
            if comparison.match():
                return True
        return False

    def _record_system_moves_seen(self, moves):
        self._system_moves_seen.append(self._create_observed_move(self._current_entry_index, moves))

    def _create_observed_move(self, entry_index, moves):
        return {
            REQUIRE_OUTCOME_ENTRY_INDEX: entry_index,
            REQUIRE_OUTCOME_MOVES: moves,
        }

    def _create_required_outcome(self, moves, entry_index=None):
        return {
            REQUIRE_OUTCOME_ENTRY_INDEX: entry_index,
            REQUIRE_OUTCOME_MOVES: moves,
        }

    def _with_run_metadata(self, response, transcripts, runs_executed):
        response["transcript"] = self._join_transcripts(transcripts)
        response["runs_executed"] = runs_executed
        return response

    def _missing_required_outcomes_response(self, required_outcomes, outcomes_seen, transcripts, runs_executed):
        missing = [
            outcome[REQUIRE_OUTCOME_MOVES] for index, outcome in enumerate(required_outcomes)
            if not outcomes_seen[index]
        ]
        failure_description = (f"Required outcomes not observed after {runs_executed} run(s): {json.dumps(missing)}")
        self._progress.fail(failure_description)
        return {
            "success": False,
            "failure_description": failure_description,
            "transcript": self._join_transcripts(transcripts),
            "runs_executed": runs_executed,
        }

    def _join_transcripts(self, transcripts):
        if not transcripts:
            return ""
        return "\n".join(transcripts)

    def _stop_clock(self):
        self._end_time = time.time() - (self._progress.callback_seconds - self._clock_callback_seconds)
