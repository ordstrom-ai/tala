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


class TestInteractionProgress:
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

    def _given_client(self, monkeypatch):
        self._client = Mock(spec=TDMClient)
        for name in (
            "start_session", "request_speech_input", "request_semantic_input", "request_passivity", "make_request"
        ):
            getattr(self._client, name).side_effect = lambda *args, **kwargs: copy.deepcopy(self._response)
        monkeypatch.setattr(f"{TESTER_MODULE}.TDMClient", Mock(return_value=self._client))

    def _given_clock(self, monkeypatch):
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

    def _when_running_test(self, on_event=None):
        self._tester = InteractionTester(None, on_event=on_event)
        self._result = self._tester.run_testcase(self._case, offer={"credentials": PRIVATE_DATA})

    def _events_named(self, name):
        return [event for event in self._events if event["event"] == name]

    def _then_no_private_data_in_events(self):
        assert PRIVATE_DATA not in json.dumps(self._events)

    def test_events_arrive_in_execution_order_and_preserve_result(self, monkeypatch):
        self._given_client(monkeypatch)
        self._given_clock(monkeypatch)
        self._when_running_test(self._events.append)

        assert [event["event"] for event in self._events] == [
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
        ]
        assert [event["sequence"] for event in self._events] == list(range(1, len(self._events) + 1))
        assert all(event["schema_version"] == 1 for event in self._events)
        assert len({event["execution_id"] for event in self._events}) == 1
        assert len({event["testcase_id"] for event in self._events}) == 1
        assert self._events[0]["execution_id"] != self._events[0]["testcase_id"]
        assert self._events[0]["testcase_id"] != self._tester._session_id
        assert self._events[0]["data"] == {"entry_count": 2}
        assert self._events[0]["attempt_index"] is None
        assert self._events[-1]["entry_index"] is None
        assert self._events[-1]["data"] == {"status": "passed", "result": self._result, "raised": False}
        assert [(event["entry_index"], event["speaker"])
                for event in self._events_named("entry_started")] == [(0, "user"), (1, "system")]
        assert "".join(event["data"]["text"]
                       for event in self._events_named("transcript_delta")) == self._result["transcript"]
        assert self._result["running_time"] == 3.0
        assert self._result["avg_turn_time"] == 2.0
        self._then_no_private_data_in_events()

    def test_existing_positional_api_and_result_without_callback(self, monkeypatch):
        self._given_client(monkeypatch)
        self._given_clock(monkeypatch)
        tester = InteractionTester(None, "custom-device", False)
        result = tester.run_testcase(self._case, {"credentials": PRIVATE_DATA})

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
        assert self._client.start_session.call_args.args[0]["device_id"] == "custom-device"
        assert self._client.start_session.call_args.args[0]["credentials"] == PRIVATE_DATA

    def test_progress_does_not_consume_an_interaction_iterator(self, monkeypatch):
        self._given_client(monkeypatch)
        self._case["interaction"] = iter(self._case["interaction"])
        self._when_running_test(self._events.append)

        assert self._result["success"]
        assert self._events[0]["data"] == {"entry_count": None}
        assert len(self._events_named("entry_completed")) == 2

    def test_progress_is_visible_while_backend_request_is_blocked(self, monkeypatch):
        self._given_client(monkeypatch)
        request_started = threading.Event()
        release_request = threading.Event()

        def on_event(event):
            self._events.append(event)
            if event["event"] == "request_started" and event["data"]["request_type"] == "speech_input":
                request_started.set()

        def blocked_request(*args):
            assert release_request.wait(5), "Test did not release the mocked backend request"
            return copy.deepcopy(self._response)

        self._client.request_speech_input.side_effect = blocked_request
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(InteractionTester(None, on_event=on_event).run_testcase, self._case)
            try:
                assert request_started.wait(5), "No progress arrived before the backend completed"
                assert not future.done()
                assert not self._events_named("test_completed")
                assert any(event["data"]["text"] == "U> Hello\n" for event in self._events_named("transcript_delta"))
            finally:
                release_request.set()
            assert future.result(timeout=5)["success"]

    @pytest.mark.parametrize("field,expected", [("move_content", ["answer(wrong)"]), ("speech_content", "Different")])
    def test_actual_output_precedes_failed_assertion(self, monkeypatch, field, expected):
        self._given_client(monkeypatch)
        self._case["interaction"][1][field] = expected
        self._when_running_test(self._events.append)

        output = self._events_named("system_output")[0]
        completed = self._events_named("entry_completed")[-1]
        assert output["data"] == {"moves": ["answer(ok)"], "utterance": "Hello", "expected_passivity": 3.0}
        assert output["sequence"] < completed["sequence"]
        assert completed["data"]["status"] == "failed"
        assert completed["data"]["failure_description"] == self._result["failure_description"]
        assert self._events[-1]["data"]["result"] == self._result
        assert not self._result["success"]
        self._then_no_private_data_in_events()

    @pytest.mark.parametrize("missing", ["moves", "utterance", "output"])
    def test_missing_output_diagnostics_are_sanitized_only_in_events(self, monkeypatch, missing):
        self._given_client(monkeypatch)
        if missing == "output":
            del self._response["output"]
        else:
            del self._response["output"][missing]
        self._when_running_test(self._events.append)

        assert not self._result["success"]
        assert PRIVATE_DATA in self._result["failure_description"]
        assert PRIVATE_DATA in self._result["transcript"]
        assert not self._events[-1]["data"]["result"]["success"]
        self._then_no_private_data_in_events()

    @pytest.mark.parametrize("observe", [False, True])
    def test_session_start_exception_still_propagates(self, monkeypatch, observe):
        self._given_client(monkeypatch)
        error = RuntimeError(PRIVATE_DATA)
        self._client.start_session.side_effect = error
        tester = InteractionTester(None, on_event=self._events.append if observe else None)

        with pytest.raises(RuntimeError) as raised:
            tester.run_testcase(self._case)
        assert raised.value is error
        if observe:
            assert self._events_named("request_completed")[-1]["data"]["success"] is False
            assert self._events_named("attempt_completed")[-1]["data"]["raised"] is True
            assert self._events[-1]["event"] == "test_completed"
            assert self._events[-1]["data"]["status"] == "error"
            assert self._events[-1]["data"]["error_type"] == "RuntimeError"
        self._then_no_private_data_in_events()

    def test_handled_request_exception_retains_legacy_diagnostics(self, monkeypatch):
        self._given_client(monkeypatch)
        self._client.request_speech_input.side_effect = RuntimeError(PRIVATE_DATA)
        self._when_running_test(self._events.append)

        assert not self._result["success"]
        assert PRIVATE_DATA in self._result["failure_description"]
        assert PRIVATE_DATA in self._result["transcript"]
        assert self._events[-1]["data"]["status"] == "error"
        assert self._events[-1]["data"]["raised"] is False
        assert self._events[-1]["data"]["error_type"] == "InteractionTesterException"
        self._then_no_private_data_in_events()

    @pytest.mark.parametrize(
        "input_type,request_type", [("moves", "semantic_input"), ("interpretations", "semantic_input"),
                                    ("passivity", "passivity")]
    )
    def test_other_user_inputs_emit_request_progress(self, monkeypatch, input_type, request_type):
        self._given_client(monkeypatch)
        if input_type == "moves":
            entry = {"move_content": ["ask(question)"]}
        elif input_type == "interpretations":
            entry = {
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
            }
        else:
            entry = {"expected_passivity": 3.0}
        self._case["interaction"][0] = {"speaker": "user", **entry}
        self._when_running_test(self._events.append)

        assert self._result["success"]
        assert [event["data"]["request_type"]
                for event in self._events_named("request_started")] == ["start_session", request_type]

    @pytest.mark.parametrize("observe", [False, True])
    def test_speech_streaming_is_independent_of_progress_callback(self, monkeypatch, observe):
        self._given_client(monkeypatch)
        self._given_clock(monkeypatch)
        listener = Mock(system_utterance="Streamed hello", streaming_started=1001.5, streaming_ended=1003.0)
        monkeypatch.setattr(f"{TESTER_MODULE}.StreamListener", Mock(return_value=listener))
        self._case["interaction"][1]["speech_content"] = "Streamed hello"
        tester = InteractionTester(None, use_streaming=True, on_event=self._events.append if observe else None)
        result = tester.run_testcase(self._case)

        assert result["success"]
        assert result["avg_stream_start"] == 0.5
        assert result["avg_streaming_time"] == 1.5
        if observe:
            assert self._events_named("system_output")[0]["data"]["utterance"] == "Streamed hello"
            assert self._events[-1]["data"]["result"] == result

    def _given_service_request(self, service):
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
        if service == "query":
            response.update(predicate="query", min_results=0, max_results=1)
        elif service == "validation":
            response["validator_name"] = "validator"
        else:
            response["action_name"] = "action"
        self._client.request_speech_input.side_effect = lambda *args: copy.deepcopy(response)

    @pytest.mark.parametrize(
        "service,result_request", [("query", "query_results"), ("validation", "validation_results"),
                                   ("action", "action_results")]
    )
    def test_external_service_and_results_requests_emit_progress(self, monkeypatch, service, result_request):
        self._given_client(monkeypatch)
        self._given_service_request(service)
        post = Mock(return_value=Mock(text=json.dumps({"status": "success", "data": {"result": []}})))
        monkeypatch.setattr(f"{TESTER_MODULE}.requests.post", post)
        self._when_running_test(self._events.append)

        assert self._result["success"]
        assert [event["data"]["request_type"] for event in self._events_named("request_started")] == [
            "start_session",
            "speech_input",
            f"service_{service}",
            result_request,
        ]
        assert all(event["data"]["success"] for event in self._events_named("request_completed"))
        assert self._client.make_request.call_count == 1
        self._then_no_private_data_in_events()

    @pytest.mark.parametrize("observe", [False, True])
    @pytest.mark.parametrize("body", [PRIVATE_DATA, json.dumps({"status": "failure", "error": PRIVATE_DATA})])
    def test_service_query_exception_still_propagates(self, monkeypatch, observe, body):
        self._given_client(monkeypatch)
        self._given_service_request("query")
        monkeypatch.setattr(f"{TESTER_MODULE}.requests.post", Mock(return_value=Mock(text=body)))
        tester = InteractionTester(None, on_event=self._events.append if observe else None)

        with pytest.raises(QueryException) as raised:
            tester.run_testcase(self._case)
        assert PRIVATE_DATA in str(raised.value)
        if observe:
            assert self._events[-1]["data"]["status"] == "error"
            assert self._events[-1]["data"]["error_type"] == "QueryException"
            assert len(self._events_named("entry_completed")) == 2
        self._then_no_private_data_in_events()

    def _given_repeated_test(self, moves, repeat=5):
        self._case["repeat"] = repeat
        self._case["interaction"][1]["move_content"] = [["answer(one)"], ["answer(two)"]]
        responses = [copy.deepcopy(self._response) for _ in moves]
        for response, move in zip(responses, moves):
            response["output"]["moves"] = [move]
        self._client.request_speech_input.side_effect = responses

    def test_repetitions_stop_when_required_outcomes_are_seen(self, monkeypatch):
        self._given_client(monkeypatch)
        self._given_repeated_test(["answer(one)", "answer(two)"])
        self._case["require_outcomes"] = [{
            "entry_index": 1,
            "moves": ["answer(one)"]
        }, {
            "entry_index": 1,
            "moves": ["answer(two)"]
        }]
        self._when_running_test(self._events.append)

        assert [event["attempt_index"] for event in self._events_named("attempt_started")] == [1, 2]
        assert all(event["attempt_count"] == 5 for event in self._events)
        assert all(event["data"]["status"] == "passed" for event in self._events_named("attempt_completed"))
        assert self._result["runs_executed"] == 2
        assert self._events[-1]["data"]["result"] == self._result
        assert "".join(event["data"]["text"]
                       for event in self._events_named("transcript_delta")) == self._result["transcript"]

    def test_missing_required_outcomes_fail_only_the_final_test(self, monkeypatch):
        self._given_client(monkeypatch)
        self._given_repeated_test(["answer(one)", "answer(one)"], repeat=2)
        self._case["require_outcomes"] = [["answer(two)"]]
        self._when_running_test(self._events.append)

        assert all(event["data"]["status"] == "passed" for event in self._events_named("attempt_completed"))
        assert self._events[-1]["data"]["status"] == "failed"
        assert self._result["runs_executed"] == 2
        assert self._events[-1]["data"]["result"] == self._result

    def test_failed_repetition_stops_remaining_attempts(self, monkeypatch):
        self._given_client(monkeypatch)
        self._given_repeated_test(["answer(wrong)"])
        self._when_running_test(self._events.append)

        assert len(self._events_named("attempt_completed")) == 1
        assert self._events[-1]["data"]["status"] == "failed"
        assert self._result["runs_executed"] == 1

    def test_observer_latency_does_not_inflate_legacy_timings(self, monkeypatch):
        self._given_client(monkeypatch)
        self._given_clock(monkeypatch)

        def slow_observer(event):
            self._events.append(event)
            self._now += 10.0

        self._when_running_test(slow_observer)

        assert self._result["running_time"] == 3.0
        assert self._result["avg_turn_time"] == 2.0
        assert self._result["max_turn_time"] == 2.0
        assert [event["data"]["elapsed_seconds"] for event in self._events_named("request_completed")] == [1.0, 2.0]
        assert [event["data"]["elapsed_seconds"] for event in self._events_named("entry_completed")] == [2.0, 0.0]

    def test_observer_exceptions_do_not_fail_or_leak_into_the_test(self, monkeypatch):
        self._given_client(monkeypatch)
        warning = Mock()
        monkeypatch.setattr("tala.testing.interaction.progress.logger.warning", warning)

        def broken_observer(event):
            self._events.append(event)
            raise RuntimeError(PRIVATE_DATA)

        self._when_running_test(broken_observer)

        assert self._result["success"]
        assert PRIVATE_DATA not in self._result["transcript"]
        assert self._events[-1]["event"] == "test_completed"
        assert warning.call_count == len(self._events)
        assert all(call.kwargs == {"error_type": "RuntimeError"} for call in warning.call_args_list)

    def test_observer_cannot_mutate_backend_or_final_result(self, monkeypatch):
        self._given_client(monkeypatch)

        def mutating_observer(event):
            if event["event"] == "system_output":
                event["data"]["moves"].clear()
            if event["event"] in ("attempt_completed", "test_completed"):
                event["data"]["result"]["success"] = False

        self._when_running_test(mutating_observer)
        assert self._result["success"]
        assert self._tester._latest_response["output"]["moves"] == ["answer(ok)"]

    def test_reusing_tester_starts_a_new_event_execution(self, monkeypatch):
        self._given_client(monkeypatch)
        tester = InteractionTester(None, on_event=self._events.append)
        tester.run_testcase(self._case)
        tester.run_testcase(self._case)

        starts = self._events_named("test_started")
        assert starts[0]["execution_id"] != starts[1]["execution_id"]
        assert starts[0]["testcase_id"] != starts[1]["testcase_id"]
        assert [event["sequence"] for event in starts] == [1, 1]
        assert starts[0]["session_id"] == starts[1]["session_id"]

    def test_concurrent_testers_have_isolated_progress(self, monkeypatch):
        self._given_client(monkeypatch)
        events = [[], []]
        testers = [InteractionTester(None, on_event=events[index].append) for index in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda tester: tester.run_testcase(self._case), testers))

        assert all(result["success"] for result in results)
        assert events[0][0]["execution_id"] != events[1][0]["execution_id"]
        assert events[0][0]["testcase_id"] != events[1][0]["testcase_id"]
        assert events[0][0]["session_id"] != events[1][0]["session_id"]
        for messages in events:
            assert [event["sequence"] for event in messages] == list(range(1, len(messages) + 1))

    @pytest.mark.parametrize("observe", [False, True])
    def test_executor_accepts_optional_callback_without_changing_return(self, monkeypatch, observe):
        self._given_client(monkeypatch)
        executor = InteractionTestExecutorNoAssert()
        args = [self._case, None, False, {"credentials": PRIVATE_DATA}]
        if observe:
            args.append(self._events.append)
        assert executor.run_ng_interaction_test(*args) is None
        assert executor.result["success"]
        if observe:
            assert self._events[-1]["data"]["result"] == executor.result

    def test_asserting_executor_still_raises_after_completion_event(self, monkeypatch, capsys):
        self._given_client(monkeypatch)
        self._case["interaction"][1]["speech_content"] = "Different"
        executor = InteractionTestExecutorAssert()
        with pytest.raises(AssertionError):
            executor.run_ng_interaction_test(self._case, on_event=self._events.append)

        assert self._events[-1]["data"]["status"] == "failed"
        assert "Begin interaction test" in capsys.readouterr().out

    def test_consecutive_speaker_exception_keeps_existing_behavior(self, monkeypatch):
        self._given_client(monkeypatch)
        self._case["interaction"][1] = {"speaker": "user", "speech_content": "Again"}
        self._when_running_test(self._events.append)

        assert not self._result["success"]
        assert "Two consecutive entries" in self._result["failure_description"]
        assert self._events[-1]["data"]["error_type"] == InteractionTesterException.__name__
