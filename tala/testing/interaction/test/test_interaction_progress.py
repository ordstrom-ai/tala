from concurrent.futures import ThreadPoolExecutor
import copy
import json
import threading
from unittest.mock import Mock

import pytest

from tala.testing.interaction.interaction_test_executor import InteractionTestExecutorAssert
from tala.testing.interaction.interaction_test_executor import InteractionTestExecutorNoAssert
from tala.testing.interaction.interaction_tester import InteractionTester
from tala.testing.interaction.interaction_tester import InteractionTesterException
from tala.testing.interaction.interaction_tester import QueryException
from tala.utils.tdm_client import TDMClient

TESTER_MODULE = "tala.testing.interaction.interaction_tester"
PRIVATE_DATA = "private-backend-data"
USER_INPUT_VARIANTS = {
    "moves": {
        "move_content": ["ask(question)"]
    },
    "interpretations": {
        "utterance": "Hello",
        "interpretations": [{
            "moves": [{
                "ddd": "example_ddd",
                "semantic_expression": "ask(question)",
                "perception_confidence": 1.0,
                "understanding_confidence": 1.0,
            }],
            "modality": "other",
        }],
    },
    "passivity": {
        "expected_passivity": 3.0
    },
}
SERVICE_INVOCATION_FIELDS = {
    "query": {
        "predicate": "query",
        "min_results": 0,
        "max_results": 1
    },
    "validation": {
        "validator_name": "validator"
    },
    "action": {
        "action_name": "action"
    },
}


class InteractionProgressTestCase:
    def setup_method(self):
        self._events = []
        self._case = {
            "name": "example",
            "target_ddd": "example_ddd",
            "url": "https://example.invalid/interact",
            "interaction": [
                {
                    "speaker": "user",
                    "speech_content": "Hello"
                },
                {
                    "speaker": "system",
                    "move_content": ["answer(ok)"],
                    "speech_content": "Hello"
                },
            ],
        }
        self._response = {
            "session": {
                "encrypted_data": PRIVATE_DATA
            },
            "output": {
                "moves": ["answer(ok)"],
                "utterance": "Hello",
                "expected_passivity": 3.0,
                "encrypted_data": PRIVATE_DATA,
                "visual_output": PRIVATE_DATA,
            },
            "context": {
                "credentials": PRIVATE_DATA
            },
        }

    def given_mocked_tdm_client(self, monkeypatch):
        self._client = Mock(spec=TDMClient)
        for name in (
            "start_session", "request_speech_input", "request_semantic_input", "request_passivity", "make_request"
        ):
            getattr(self._client, name).side_effect = lambda *args, **kwargs: copy.deepcopy(self._response)
        monkeypatch.setattr(f"{TESTER_MODULE}.TDMClient", Mock(return_value=self._client))

    def given_deterministic_clock(self, monkeypatch):
        self._now = 1000.0
        monkeypatch.setattr(f"{TESTER_MODULE}.time.time", lambda: self._now)
        monkeypatch.setattr(f"{TESTER_MODULE}.time.perf_counter", lambda: self._now)

        def start_session(*args):
            self._now += 1.0
            return copy.deepcopy(self._response)

        def speech_input(*args):
            self._now += 2.0
            return copy.deepcopy(self._response)

        self._client.start_session.side_effect = start_session
        self._client.request_speech_input.side_effect = speech_input

    def when_interaction_tester_runs(self, on_event=None):
        self._tester = InteractionTester(None, on_event=on_event)
        self._result = self._tester.run_testcase(self._case, offer={"credentials": PRIVATE_DATA})

    def when_legacy_positional_call_runs(self):
        self._tester = InteractionTester(None, "custom-device", False)
        self._result = self._tester.run_testcase(self._case, {"credentials": PRIVATE_DATA})

    def when_interaction_tester_runs_with_speech_streaming(self, observe):
        self._tester = InteractionTester(None, use_streaming=True, on_event=self._events.append if observe else None)
        self._result = self._tester.run_testcase(self._case)

    def given_user_turn(self, turn):
        self._case["interaction"][0] = {"speaker": "user", **turn}

    def given_user_input_variant(self, input_type):
        self.given_user_turn(USER_INPUT_VARIANTS[input_type])

    def given_system_expectation(self, field, expected):
        self._case["interaction"][1][field] = expected

    def given_system_response_without(self, field):
        if field == "output":
            self._response.pop("output")
        else:
            self._response["output"].pop(field)

    def given_required_outcomes(self, outcomes):
        self._case["require_outcomes"] = outcomes

    def given_session_start_failure(self, error):
        self._client.start_session.side_effect = error

    def given_speech_input_failure(self, error):
        self._client.request_speech_input.side_effect = error

    def given_progress_observation(self, enabled):
        self._on_event = self._events.append if enabled else None

    def when_interaction_tester_raises(self, error_type):
        with pytest.raises(error_type) as raised:
            InteractionTester(None, on_event=self._on_event).run_testcase(self._case)
        self._raised_error = raised.value

    def given_backend_request_waits_for_release(self):
        self._request_started = threading.Event()
        self._release_request = threading.Event()

        def observe_request_started(event):
            self._events.append(event)
            if event["event"] == "request_started" and event["data"]["request_type"] == "speech_input":
                self._request_started.set()

        def wait_for_release(*args):
            assert self._release_request.wait(5), "Test did not release the mocked backend request"
            return copy.deepcopy(self._response)

        self._on_event = observe_request_started
        self._client.request_speech_input.side_effect = wait_for_release

    def when_test_runs_in_background(self):
        self._thread_pool = ThreadPoolExecutor(max_workers=1)
        self._future = self._thread_pool.submit(
            InteractionTester(None, on_event=self._on_event).run_testcase, self._case
        )

    def when_backend_request_is_released(self):
        self._release_request.set()

    def then_user_turn_progress_arrived_before_test_completion(self):
        assert self._request_started.wait(5), "No progress arrived before the backend completed"
        assert not self._future.done()
        assert not self.events_named("test_completed")
        assert any(event["data"]["text"] == "U> Hello\n" for event in self.events_named("transcript_delta"))

    def then_background_test_succeeds(self):
        try:
            assert self._future.result(timeout=5)["success"]
        finally:
            self._thread_pool.shutdown()

    def given_speech_stream_listener(self, monkeypatch, utterance):
        listener = Mock(system_utterance=utterance, streaming_started=1001.5, streaming_ended=1003.0)
        monkeypatch.setattr(f"{TESTER_MODULE}.StreamListener", Mock(return_value=listener))
        self.given_system_expectation("speech_content", utterance)

    def given_slow_progress_observer(self):
        def observe_slowly(event):
            self._events.append(event)
            self._now += 10.0

        self._on_event = observe_slowly

    def given_failing_progress_observer(self, monkeypatch):
        self._warning = Mock()
        monkeypatch.setattr("tala.testing.interaction.progress.logger.warning", self._warning)

        def fail_to_observe(event):
            self._events.append(event)
            raise RuntimeError(PRIVATE_DATA)

        self._on_event = fail_to_observe

    def given_mutating_progress_observer(self):
        def mutate_event(event):
            if event["event"] == "system_output":
                event["data"]["moves"].clear()
            if event["event"] in ("attempt_completed", "test_completed"):
                event["data"]["result"]["success"] = False

        self._on_event = mutate_event

    def when_same_tester_runs_twice(self):
        self._tester = InteractionTester(None, on_event=self._events.append)
        self._tester.run_testcase(self._case)
        self._tester.run_testcase(self._case)

    def when_two_testers_run_concurrently(self):
        self._concurrent_events = [[], []]
        testers = [InteractionTester(None, on_event=events.append) for events in self._concurrent_events]
        with ThreadPoolExecutor(max_workers=2) as pool:
            self._concurrent_results = list(pool.map(lambda tester: tester.run_testcase(self._case), testers))

    def when_executor_runs(self, observe):
        self._executor = InteractionTestExecutorNoAssert()
        self._executor.run_ng_interaction_test(
            self._case,
            offer={"credentials": PRIVATE_DATA},
            on_event=self._events.append if observe else None,
        )

    def when_asserting_executor_runs(self):
        self._executor = InteractionTestExecutorAssert()
        with pytest.raises(AssertionError):
            self._executor.run_ng_interaction_test(self._case, on_event=self._events.append)

    def given_consecutive_user_turns(self):
        self._case["interaction"][1] = {"speaker": "user", "speech_content": "Again"}

    def given_interaction_iterator(self):
        self._case["interaction"] = iter(self._case["interaction"])

    def then_interaction_iterator_length_is_unknown(self):
        assert self._events[0]["data"]["entry_count"] is None
        assert len(self.events_named("entry_completed")) == 2

    def then_session_uses_expected_device_and_offer(self):
        session = self._client.start_session.call_args.args[0]
        assert session["device_id"] == "custom-device"
        assert session["credentials"] == PRIVATE_DATA

    def then_asserting_executor_reports_failure(self, capsys):
        assert self._events[-1]["data"]["status"] == "failed"
        assert "Begin interaction test" in capsys.readouterr().out

    def events_named(self, name):
        return [event for event in self._events if event["event"] == name]

    def then_no_private_data_in_events(self):
        assert PRIVATE_DATA not in json.dumps(self._events)

    def then_event_sequence_matches(self, expected_events):
        assert [event["event"] for event in self._events] == expected_events
        assert [event["sequence"] for event in self._events] == list(range(1, len(self._events) + 1))
        assert all(event["schema_version"] == 1 for event in self._events)
        assert len({event["execution_id"] for event in self._events}) == 1
        assert len({event["testcase_id"] for event in self._events}) == 1

    def then_completion_matches_result(self, expected_status):
        completed = self.events_named("test_completed")[-1]
        assert completed["data"]["status"] == expected_status
        assert completed["data"]["result"] == self._result
        assert completed["data"]["raised"] is False

    def then_entry_contexts_are(self, expected_contexts):
        contexts = [(event["entry_index"], event["speaker"]) for event in self.events_named("entry_started")]
        assert contexts == expected_contexts

    def then_transcript_deltas_reconstruct_result(self):
        transcript = "".join(event["data"]["text"] for event in self.events_named("transcript_delta"))
        assert transcript == self._result["transcript"]

    def then_timing_metrics_are(self, running_time, average_turn_time):
        assert self._result["running_time"] == running_time
        assert self._result["avg_turn_time"] == average_turn_time

    def then_result_has_success(self, success):
        assert self._result["success"] is success

    def then_request_types_are(self, expected_request_types):
        request_types = [event["data"]["request_type"] for event in self.events_named("request_started")]
        assert request_types == expected_request_types

    def then_legacy_result_is(self, result, tester):
        assert result == {
            "success": True,
            "name": "example",
            "session_id": tester._session_id,
            "transcript": '\n=== Begin interaction test "example" ===\nU> Hello\n'
            'S> ["answer(ok)"]: 2.00 s\nS> Hello: 2.00 s\n=== End interaction test ===\n',
            "start_time": 1000.0,
            "running_time": 3.0,
            "avg_turn_time": 2.0,
            "max_turn_time": 2.0,
        }

    def then_failure_retains_legacy_diagnostics(self):
        assert PRIVATE_DATA in self._result["failure_description"]
        assert PRIVATE_DATA in self._result["transcript"]
        self.then_no_private_data_in_events()

    def then_requests_completed_successfully(self):
        assert all(event["data"]["success"] for event in self.events_named("request_completed"))

    def then_service_results_are_returned_to_tdm(self):
        assert self._client.make_request.call_count == 1

    def then_progress_result_records_failure(self):
        assert self._result["success"] is False
        assert self._events[-1]["data"]["result"]["success"] is False

    def then_query_error_contains(self, text):
        assert text in str(self._raised_error)

    def then_query_error_request_progress_is(self, observe):
        if observe:
            self.then_request_failure_is_reported("QueryException")
            assert len(self.events_named("entry_completed")) == 2
        self.then_progress_contains_no_private_data()

    def then_attempt_count_is(self, count):
        assert all(event["attempt_count"] == count for event in self._events)

    def then_observer_latency_is_excluded(self):
        self.then_timing_metrics_are(3.0, 2.0)
        assert self._result["max_turn_time"] == 2.0
        request_times = [event["data"]["elapsed_seconds"] for event in self.events_named("request_completed")]
        entry_times = [event["data"]["elapsed_seconds"] for event in self.events_named("entry_completed")]
        assert request_times == [1.0, 2.0]
        assert entry_times == [2.0, 0.0]

    def then_observer_error_does_not_change_transcript(self):
        self.then_result_has_success(True)
        assert PRIVATE_DATA not in self._result["transcript"]

    def then_session_start_error_is_preserved(self, expected_error):
        assert self._raised_error is expected_error
        if self._on_event is not None:
            assert self.events_named("request_completed")[-1]["data"]["success"] is False
            assert self.events_named("attempt_completed")[-1]["data"]["raised"] is True
            assert self._events[-1]["data"]["status"] == "error"
            assert self._events[-1]["data"]["error_type"] == "RuntimeError"
        self.then_no_private_data_in_events()

    def then_request_failure_is_reported(self, error_type):
        completion = self._events[-1]["data"]
        assert completion["status"] == "error"
        assert completion["error_type"] == error_type

    def then_handled_request_failure_is(self, error_type):
        self.then_request_failure_is_reported(error_type)
        assert self._events[-1]["data"]["raised"] is False

    def then_progress_contains_no_private_data(self):
        self.then_no_private_data_in_events()

    def then_streamed_utterance_is_used(self, utterance):
        assert self.events_named("system_output")[0]["data"]["utterance"] == utterance

    def then_streaming_metrics_are_reported(self):
        assert self._result["avg_stream_start"] == 0.5
        assert self._result["avg_streaming_time"] == 1.5

    def then_streaming_result_is_reported(self):
        assert self._events[-1]["data"]["result"] == self._result

    def then_streaming_output_matches(self, observe, utterance):
        if observe:
            self.then_streamed_utterance_is_used(utterance)
            self.then_streaming_result_is_reported()

    def then_all_repetitions_passed(self):
        assert all(event["data"]["status"] == "passed" for event in self.events_named("attempt_completed"))

    def then_attempt_indices_are(self, expected_indices):
        indices = [event["attempt_index"] for event in self.events_named("attempt_started")]
        assert indices == expected_indices

    def then_runs_executed_is(self, count):
        assert self._result["runs_executed"] == count

    def then_observer_failures_were_logged_without_payloads(self):
        assert self._events[-1]["event"] == "test_completed"
        assert self._warning.call_count == len(self._events)
        assert all(call.kwargs == {"error_type": "RuntimeError"} for call in self._warning.call_args_list)

    def then_parallel_runs_are_isolated(self):
        assert all(result["success"] for result in self._concurrent_results)
        first, second = (events[0] for events in self._concurrent_events)
        assert first["execution_id"] != second["execution_id"]
        assert first["testcase_id"] != second["testcase_id"]
        assert first["session_id"] != second["session_id"]
        for events in self._concurrent_events:
            assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))

    def then_executor_returns_successful_result(self, observe):
        assert self._executor.result["success"]
        if observe:
            assert self._events[-1]["data"]["result"] == self._executor.result

    def then_tester_reuse_has_distinct_execution_ids(self):
        starts = self.events_named("test_started")
        assert starts[0]["execution_id"] != starts[1]["execution_id"]
        assert starts[0]["testcase_id"] != starts[1]["testcase_id"]
        assert [event["sequence"] for event in starts] == [1, 1]
        assert starts[0]["session_id"] == starts[1]["session_id"]

    def then_backend_response_is_unchanged(self):
        assert self._result["success"]
        assert self._tester._latest_response["output"]["moves"] == ["answer(ok)"]

    def then_consecutive_speaker_failure_is_reported(self):
        self.then_result_has_success(False)
        assert "Two consecutive entries" in self._result["failure_description"]
        assert self._events[-1]["data"]["error_type"] == InteractionTesterException.__name__

    def then_output_precedes_assertion_failure(self, expected_output):
        output = self.events_named("system_output")[0]
        completed = self.events_named("entry_completed")[-1]
        assert output["data"] == expected_output
        assert output["sequence"] < completed["sequence"]
        assert completed["data"]["status"] == "failed"
        assert completed["data"]["failure_description"] == self._result["failure_description"]
        assert self.events_named("test_completed")[-1]["data"]["result"] == self._result
        self.then_result_has_success(False)

    def then_envelope_ids_are_independent(self):
        first = self._events[0]
        assert first["execution_id"] != first["testcase_id"]
        assert first["testcase_id"] != self._tester._session_id
        assert first["data"] == {"entry_count": 2}
        assert first["attempt_index"] is None
        assert self._events[-1]["entry_index"] is None

    def given_external_service_invocation(self, service):
        response = {
            "session": {
                "encrypted_data": PRIVATE_DATA
            },
            "parameters": {
                "value": PRIVATE_DATA
            },
            "url": f"https://example.invalid/{PRIVATE_DATA}",
            "original_request": {},
            "ddd_name": "example_ddd",
            "earlier_results": [],
        }
        response.update(SERVICE_INVOCATION_FIELDS[service])
        self._client.request_speech_input.side_effect = lambda *args: copy.deepcopy(response)

    def given_repeat_count(self, count):
        self._case["repeat"] = count

    def given_system_move_alternatives(self, alternatives):
        self.given_system_expectation("move_content", alternatives)

    def given_speech_input_responses_with_moves(self, moves):
        responses = [copy.deepcopy(self._response) for _ in moves]
        for response, move in zip(responses, moves):
            response["output"]["moves"] = [move]
        self._client.request_speech_input.side_effect = responses

    def given_http_service_response(self, monkeypatch, body):
        response = Mock(text=body)
        monkeypatch.setattr(f"{TESTER_MODULE}.requests.post", Mock(return_value=response))

    def given_assertion_failure(self):
        self.given_system_expectation("speech_content", "Different")


class TestInteractionProgressLifecycle(InteractionProgressTestCase):
    def test_events_arrive_in_execution_order_and_preserve_result(self, monkeypatch):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_deterministic_clock(monkeypatch)
        self.when_interaction_tester_runs(self._events.append)

        self.then_event_sequence_matches([
            "test_started",
            "attempt_started",
            "transcript_delta",
            "request_started",
            "request_completed",
            "entry_started",
            "transcript_delta",
            "request_started",
            "request_completed",
            "entry_completed",
            "entry_started",
            "system_output",
            "transcript_delta",
            "transcript_delta",
            "entry_completed",
            "transcript_delta",
            "attempt_completed",
            "test_completed",
        ])
        self.then_envelope_ids_are_independent()
        self.then_completion_matches_result("passed")
        self.then_entry_contexts_are([(0, "user"), (1, "system")])
        self.then_transcript_deltas_reconstruct_result()
        self.then_timing_metrics_are(3.0, 2.0)
        self.then_no_private_data_in_events()

    def test_existing_positional_api_and_result_without_callback(self, monkeypatch):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_deterministic_clock(monkeypatch)
        self.when_legacy_positional_call_runs()

        self.then_legacy_result_is(self._result, self._tester)
        self.then_session_uses_expected_device_and_offer()

    def test_progress_does_not_consume_an_interaction_iterator(self, monkeypatch):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_interaction_iterator()
        self.when_interaction_tester_runs(self._events.append)

        self.then_result_has_success(True)
        self.then_interaction_iterator_length_is_unknown()

    def test_progress_is_visible_while_backend_request_is_blocked(self, monkeypatch):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_backend_request_waits_for_release()
        self.when_test_runs_in_background()
        try:
            self.then_user_turn_progress_arrived_before_test_completion()
        finally:
            self.when_backend_request_is_released()
        self.then_background_test_succeeds()


class TestInteractionProgressAssertions(InteractionProgressTestCase):
    @pytest.mark.parametrize("field,expected", [("move_content", ["answer(wrong)"]), ("speech_content", "Different")])
    def test_actual_output_precedes_failed_assertion(self, monkeypatch, field, expected):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_system_expectation(field, expected)
        self.when_interaction_tester_runs(self._events.append)

        self.then_output_precedes_assertion_failure({
            "moves": ["answer(ok)"],
            "utterance": "Hello",
            "expected_passivity": 3.0
        })
        self.then_no_private_data_in_events()

    @pytest.mark.parametrize("missing", ["moves", "utterance", "output"])
    def test_missing_output_diagnostics_are_sanitized_only_in_events(self, monkeypatch, missing):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_system_response_without(missing)
        self.when_interaction_tester_runs(self._events.append)

        self.then_result_has_success(False)
        self.then_failure_retains_legacy_diagnostics()
        self.then_progress_result_records_failure()

    @pytest.mark.parametrize("observe", [False, True])
    def test_session_start_exception_still_propagates(self, monkeypatch, observe):
        self.given_mocked_tdm_client(monkeypatch)
        error = RuntimeError(PRIVATE_DATA)
        self.given_session_start_failure(error)
        self.given_progress_observation(observe)

        self.when_interaction_tester_raises(RuntimeError)

        self.then_session_start_error_is_preserved(error)

    def test_handled_request_exception_retains_legacy_diagnostics(self, monkeypatch):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_speech_input_failure(RuntimeError(PRIVATE_DATA))
        self.when_interaction_tester_runs(self._events.append)

        self.then_result_has_success(False)
        self.then_failure_retains_legacy_diagnostics()
        self.then_handled_request_failure_is("InteractionTesterException")


class TestInteractionProgressInputsAndServices(InteractionProgressTestCase):
    @pytest.mark.parametrize(
        "input_type,request_type", [("moves", "semantic_input"), ("interpretations", "semantic_input"),
                                    ("passivity", "passivity")]
    )
    def test_other_user_inputs_emit_request_progress(self, monkeypatch, input_type, request_type):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_user_input_variant(input_type)
        self.when_interaction_tester_runs(self._events.append)

        self.then_result_has_success(True)
        self.then_request_types_are(["start_session", request_type])

    @pytest.mark.parametrize("observe", [False, True])
    def test_speech_streaming_is_independent_of_progress_callback(self, monkeypatch, observe):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_deterministic_clock(monkeypatch)
        self.given_speech_stream_listener(monkeypatch, "Streamed hello")
        self.when_interaction_tester_runs_with_speech_streaming(observe)

        self.then_result_has_success(True)
        self.then_streaming_metrics_are_reported()
        self.then_streaming_output_matches(observe, "Streamed hello")

    @pytest.mark.parametrize(
        "service,result_request", [("query", "query_results"), ("validation", "validation_results"),
                                   ("action", "action_results")]
    )
    def test_external_service_and_results_requests_emit_progress(self, monkeypatch, service, result_request):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_external_service_invocation(service)
        self.given_http_service_response(monkeypatch, json.dumps({"status": "success", "data": {"result": []}}))
        self.when_interaction_tester_runs(self._events.append)

        self.then_result_has_success(True)
        self.then_request_types_are([
            "start_session",
            "speech_input",
            f"service_{service}",
            result_request,
        ])
        self.then_requests_completed_successfully()
        self.then_service_results_are_returned_to_tdm()
        self.then_no_private_data_in_events()

    @pytest.mark.parametrize("observe", [False, True])
    @pytest.mark.parametrize("body", [PRIVATE_DATA, json.dumps({"status": "failure", "error": PRIVATE_DATA})])
    def test_service_query_exception_still_propagates(self, monkeypatch, observe, body):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_external_service_invocation("query")
        self.given_http_service_response(monkeypatch, body)
        self.given_progress_observation(observe)

        self.when_interaction_tester_raises(QueryException)

        self.then_query_error_contains(PRIVATE_DATA)
        self.then_query_error_request_progress_is(observe)


class TestInteractionProgressRepeats(InteractionProgressTestCase):
    def test_repetitions_stop_when_required_outcomes_are_seen(self, monkeypatch):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_repeat_count(5)
        self.given_system_move_alternatives([["answer(one)"], ["answer(two)"]])
        self.given_speech_input_responses_with_moves(["answer(one)", "answer(two)"])
        self.given_required_outcomes([{
            "entry_index": 1,
            "moves": ["answer(one)"]
        }, {
            "entry_index": 1,
            "moves": ["answer(two)"]
        }])
        self.when_interaction_tester_runs(self._events.append)

        self.then_attempt_indices_are([1, 2])
        self.then_attempt_count_is(5)
        self.then_all_repetitions_passed()
        self.then_runs_executed_is(2)
        self.then_completion_matches_result("passed")
        self.then_transcript_deltas_reconstruct_result()

    def test_missing_required_outcomes_fail_only_the_final_test(self, monkeypatch):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_repeat_count(2)
        self.given_system_move_alternatives([["answer(one)"], ["answer(two)"]])
        self.given_speech_input_responses_with_moves(["answer(one)", "answer(one)"])
        self.given_required_outcomes([["answer(two)"]])
        self.when_interaction_tester_runs(self._events.append)

        self.then_all_repetitions_passed()
        self.then_completion_matches_result("failed")
        self.then_runs_executed_is(2)

    def test_failed_repetition_stops_remaining_attempts(self, monkeypatch):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_repeat_count(5)
        self.given_system_move_alternatives([["answer(one)"], ["answer(two)"]])
        self.given_speech_input_responses_with_moves(["answer(wrong)"])
        self.when_interaction_tester_runs(self._events.append)

        self.then_attempt_indices_are([1])
        self.then_completion_matches_result("failed")
        self.then_runs_executed_is(1)


class TestInteractionProgressObserver(InteractionProgressTestCase):
    def test_observer_latency_does_not_inflate_legacy_timings(self, monkeypatch):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_deterministic_clock(monkeypatch)
        self.given_slow_progress_observer()
        self.when_interaction_tester_runs(self._on_event)

        self.then_observer_latency_is_excluded()

    def test_observer_exceptions_do_not_fail_or_leak_into_the_test(self, monkeypatch):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_failing_progress_observer(monkeypatch)
        self.when_interaction_tester_runs(self._on_event)

        self.then_observer_error_does_not_change_transcript()
        self.then_observer_failures_were_logged_without_payloads()

    def test_observer_cannot_mutate_backend_or_final_result(self, monkeypatch):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_mutating_progress_observer()
        self.when_interaction_tester_runs(self._on_event)
        self.then_backend_response_is_unchanged()

    def test_reusing_tester_starts_a_new_event_execution(self, monkeypatch):
        self.given_mocked_tdm_client(monkeypatch)
        self.when_same_tester_runs_twice()
        self.then_tester_reuse_has_distinct_execution_ids()

    def test_concurrent_testers_have_isolated_progress(self, monkeypatch):
        self.given_mocked_tdm_client(monkeypatch)
        self.when_two_testers_run_concurrently()
        self.then_parallel_runs_are_isolated()


class TestInteractionProgressExecutors(InteractionProgressTestCase):
    @pytest.mark.parametrize("observe", [False, True])
    def test_executor_accepts_optional_callback_without_changing_return(self, monkeypatch, observe):
        self.given_mocked_tdm_client(monkeypatch)
        self.when_executor_runs(observe)
        self.then_executor_returns_successful_result(observe)

    def test_asserting_executor_still_raises_after_completion_event(self, monkeypatch, capsys):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_assertion_failure()
        self.when_asserting_executor_runs()

        self.then_asserting_executor_reports_failure(capsys)

    def test_consecutive_speaker_exception_keeps_existing_behavior(self, monkeypatch):
        self.given_mocked_tdm_client(monkeypatch)
        self.given_consecutive_user_turns()
        self.when_interaction_tester_runs(self._events.append)

        self.then_consecutive_speaker_failure_is_reported()
