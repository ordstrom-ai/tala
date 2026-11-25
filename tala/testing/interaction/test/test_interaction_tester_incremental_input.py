from copy import deepcopy
import time

from tala.testing.interaction import interaction_tester as interaction_tester_module
from tala.testing.interaction.interaction_tester import InteractionTester
from tala.testing.interaction.interaction_tester import InteractionTesterException


class TestInteractionTesterIncrementalInput:
    def test_scripted_one_turn_finishes_with_the_existing_streamed_response_path(self, monkeypatch):
        self.given_a_fake_tdm_endpoint_and_stream_listener(monkeypatch)

        self.when_the_scripted_dialogue_runs()

        self.then_the_input_events_and_streamed_final_turn_succeed()

    def test_scripted_hypothesis_revisions_finalize_before_the_normal_speech_turn(self):
        self.given_an_interaction_tester_and_a_scripted_speech_turn()

        self.when_the_incremental_user_turn_is_executed()
        self.when_the_interaction_result_is_created()

        self.then_events_precede_the_final_speech_request_and_are_recorded()

    def given_an_interaction_tester_and_a_scripted_speech_turn(self):
        self.tester = InteractionTester(port=None)
        self.tester._initialize_testcase({
            "name": "incremental speech smoke test",
            "target_ddd": "travel",
            "url": "https://handler.example/interact/offer-1",
            "incremental_input": True,
        })
        self.client = FakeInteractionTDMClient()
        self.tester._client = self.client
        self.tester._session_data = {"offer_id": "offer-1", "session_id": "session-1"}
        self.tester._previous_entry_type = "system"
        self.tester._start_clock()
        self.user_entry = {
            "speaker": "user",
            "incremental_speech_content": [
                [{
                    "utterance": "Turn",
                    "confidence": 0.72
                }],
                [{
                    "utterance": "Turn left at the next street.",
                    "confidence": 0.97
                }],
            ],
        }

    def given_a_fake_tdm_endpoint_and_stream_listener(self, monkeypatch):
        self.client = FakeInteractionTDMClient()
        self.listeners = []
        self.progress_events = []
        test_case = self

        class RecordingStreamListener(FakeStreamListener):
            def __init__(self, endpoint, session_id, logger):
                super().__init__(endpoint, session_id, logger)
                test_case.listeners.append(self)

        monkeypatch.setattr(interaction_tester_module, "TDMClient", lambda _url: self.client)
        monkeypatch.setattr(interaction_tester_module, "StreamListener", RecordingStreamListener)
        self.testcase = {
            "name": "incremental one-turn smoke test",
            "target_ddd": "travel",
            "url": "https://handler.example/interact/offer-1",
            "incremental_input": True,
            "interaction": [
                {
                    "speaker": "system",
                    "speech_content": "Welcome."
                },
                {
                    "speaker": "user",
                    "incremental_speech_content": [
                        [{
                            "utterance": "Turn",
                            "confidence": 0.72
                        }],
                        [{
                            "utterance": "Turn left at the next street.",
                            "confidence": 0.97
                        }],
                    ],
                },
                {
                    "speaker": "system",
                    "speech_content": "A streamed answer."
                },
            ],
        }

    def when_the_scripted_dialogue_runs(self):
        self.response = InteractionTester(
            port=None, use_streaming=True, on_event=self.progress_events.append
        ).run_testcase(
            self.testcase,
            offer={"offer_id": "offer-1"},
        )

    def then_the_input_events_and_streamed_final_turn_succeed(self):
        assert self.response["success"] is True
        assert self.client.calls == [
            "start_session",
            "input.utterance.hypotheses.updated",
            "input.utterance.finalized",
            "natural_language_input",
        ]
        assert self.client.final_speech_hypotheses == [{
            "utterance": "Turn left at the next street.",
            "confidence": 0.97,
        }]
        assert self.response["incremental_event_history"]
        assert self.response["avg_stream_start"] >= 0
        assert "A streamed answer." in self.response["transcript"]
        assert all(event["elapsed_seconds"] >= 0 for event in self.response["incremental_event_history"])
        assert self.client.start_request_id
        assert self.client.start_incremental_input is True
        assert self.response["session_id"] == "handler-created-session"
        assert self.listeners[0].session_id == "handler-created-session"
        assert self.listeners[0].endpoint == "https://handler-issued-sse.example/events"
        assert all(
            event["session_id"] == "handler-created-session" for event in self.progress_events
            if event["event"] == "entry_started"
        )

    def when_the_incremental_user_turn_is_executed(self):
        self.succeeded = self.tester._do_user_turn(self.user_entry)

    def when_the_interaction_result_is_created(self):
        self.tester._stop_clock()
        self.response = self.tester._create_response({"success": self.succeeded})

    def then_events_precede_the_final_speech_request_and_are_recorded(self):
        interim_event = self.client.event_requests[0]["request"]["utterance_event"]
        final_event = self.client.event_requests[1]["request"]["utterance_event"]
        assert self.succeeded is True
        assert interim_event["event_type"] == "input.utterance.hypotheses.updated"
        assert final_event["event_type"] == "input.utterance.finalized"
        assert interim_event["utterance_id"] == final_event["utterance_id"]
        assert [interim_event["sequence"], final_event["sequence"]] == [1, 2]
        assert self.client.final_speech_hypotheses == [{
            "utterance": "Turn left at the next street.",
            "confidence": 0.97,
        }]
        assert self.client.final_speech_session["request_id"] == "event-2"
        assert self.client.calls == [
            "input.utterance.hypotheses.updated",
            "input.utterance.finalized",
            "natural_language_input",
        ]
        assert [event["sequence"] for event in self.tester._incremental_event_history] == [1, 2]
        assert self.response["incremental_event_history"] == self.tester._incremental_event_history

    def test_incremental_speech_without_session_opt_in_is_rejected_before_sending_events(self):
        self.given_an_interaction_tester_and_a_scripted_speech_turn()
        self.given_the_test_case_has_not_opted_in()

        self.when_the_unopted_incremental_turn_is_attempted()

        self.then_no_incremental_requests_are_sent()

    def given_the_test_case_has_not_opted_in(self):
        self.tester._incremental_input = False

    def when_the_unopted_incremental_turn_is_attempted(self):
        self.input_error = None
        try:
            self.tester._do_user_turn(self.user_entry)
        except InteractionTesterException as error:
            self.input_error = error

    def then_no_incremental_requests_are_sent(self):
        assert self.input_error is not None
        assert self.input_error.args == ("Incremental speech requires incremental_input=true for this test case.", )
        assert self.client.calls == []

    def test_ordinary_script_does_not_opt_in_or_change_the_start_call(self, monkeypatch):
        self.given_a_fake_tdm_endpoint_and_stream_listener(monkeypatch)
        self.given_an_ordinary_speech_script()

        self.when_the_scripted_dialogue_runs()

        self.then_the_ordinary_start_has_no_incremental_arguments_or_events()

    def given_an_ordinary_speech_script(self):
        self.testcase.pop("incremental_input")
        self.testcase["interaction"][1] = {"speaker": "user", "speech_content": "Hello"}

    def then_the_ordinary_start_has_no_incremental_arguments_or_events(self):
        assert self.response["success"] is True
        assert self.client.start_request_id is None
        assert self.client.start_incremental_input is False
        assert self.client.calls == ["start_session", "natural_language_input"]
        assert "incremental_event_history" not in self.response


class FakeInteractionTDMClient:
    def __init__(self):
        self.session = None
        self.event_requests = []
        self.calls = []

    def make_request(self, request):
        self.event_requests.append(deepcopy(request))
        event = request["request"]["utterance_event"]
        self.calls.append(event["event_type"])
        response_session = deepcopy(request["session"])
        response_session["request_id"] = f"event-{event['sequence']}"
        return {
            "session": response_session,
            "utterance_event": {
                "event_id": event["event_id"],
                "event_type": event["event_type"],
                "turn_id": "server-turn-1",
                "turn_generation": 1,
                "turn_status": "open",
                "utterance_id": event["utterance_id"],
                "utterance_status": ("finalized" if event["event_type"] == "input.utterance.finalized" else "open"),
                "revision_id": event["revision_id"],
                "sequence": event["sequence"],
            },
        }

    def start_session(self, session_data, *, request_id=None, incremental_input=False):
        self.calls.append("start_session")
        self.session = deepcopy(session_data)
        self.start_request_id = request_id
        self.start_incremental_input = incremental_input
        self.session["session_id"] = "handler-created-session"
        self.session["sse_endpoint"] = "https://handler-issued-sse.example/events/"
        return {
            "output": {
                "moves": [],
                "utterance": "Welcome.",
            },
            "session": deepcopy(self.session),
        }

    def request_speech_input(self, hypotheses, session):
        self.calls.append("natural_language_input")
        self.final_speech_hypotheses = [hypothesis.as_dict() for hypothesis in hypotheses]
        self.final_speech_session = deepcopy(session)
        return {
            "output": {
                "moves": [],
                "utterance": "Unstreamed answer.",
            },
            "session": deepcopy(session),
        }


class FakeStreamListener:
    SSE_BROKER_ENDPOINT_HTTPS = "https://sse.example/event-sse"

    def __init__(self, endpoint, session_id, _logger):
        self.endpoint = endpoint
        self.session_id = session_id
        self.streaming_started = None
        self.streaming_ended = None

    def start(self):
        return None

    def wait_until_started(self):
        return None

    @property
    def system_utterance(self):
        self.streaming_started = time.time()
        self.streaming_ended = self.streaming_started + 0.01
        return "A streamed answer."

    def stop(self):
        return None
