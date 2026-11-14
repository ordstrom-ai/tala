from unittest.mock import Mock

import pytest

from tala.testing.interaction import interaction_tester
from tala.testing.interaction.interaction_tester import InteractionTester


class TrackingStreamListener:
    def __init__(self, utterance):
        self._utterance = utterance
        self.read_count = 0
        self.stop_count = 0
        self.streaming_started = 1.0
        self.streaming_ended = 2.0

    @property
    def system_utterance(self):
        self.read_count += 1
        return self._utterance

    def start(self):
        pass

    def wait_until_started(self):
        pass

    def stop(self):
        self.stop_count += 1


class TestSilentInteractionOutput:
    @pytest.mark.parametrize("utterance_state", ["empty", "null", "missing"])
    def test_move_only_response_does_not_wait_for_unrequested_speech(self, monkeypatch, utterance_state):
        self.given_silent_semantic_interaction(monkeypatch, utterance_state)
        self.when_interaction_runs()
        self.then_semantic_expectations_pass()
        self.then_listener_stops_without_reading_stream_text()

    def given_silent_semantic_interaction(self, monkeypatch, utterance_state, expected_speech=None):
        self._tester = InteractionTester(port=None, use_streaming=True)
        session = {"session_id": self._tester._session_id}
        start_response = {"session": session}
        semantic_output = {
            "moves": ["answer(visa)"],
            "expected_passivity": 5.0,
        }
        if utterance_state == "empty":
            semantic_output["utterance"] = ""
        elif utterance_state == "null":
            semantic_output["utterance"] = None
        semantic_response = {"session": session, "output": semantic_output}

        self._client = Mock()
        self._client.start_session.return_value = start_response
        self._client.request_semantic_input.return_value = semantic_response
        monkeypatch.setattr(
            interaction_tester,
            "TDMClient",
            Mock(return_value=self._client),
        )

        self._listener = TrackingStreamListener("late streamed speech")
        monkeypatch.setattr(
            interaction_tester,
            "StreamListener",
            Mock(return_value=self._listener),
        )

        system_entry = {
            "speaker": "system",
            "move_content": ["answer(visa)"],
            "expected_passivity": 5.0,
        }
        if expected_speech is not None:
            system_entry["speech_content"] = expected_speech
        self._testcase = {
            "name": "silent visa answer",
            "target_ddd": "accommodation",
            "url": "https://example.invalid/interact",
            "neural": False,
            "interaction": [
                {
                    "speaker": "user",
                    "move_content": ["answer(visa)"]
                },
                system_entry,
            ],
        }
        self._expected_speech = expected_speech

    def when_interaction_runs(self):
        self._result = self._tester.run_testcase(self._testcase)

    def then_semantic_expectations_pass(self):
        assert self._result["success"]
        assert self._tester._latest_response["output"]["moves"] == ["answer(visa)"]
        assert self._tester._latest_response["output"]["expected_passivity"] == 5.0
        if self._expected_speech is None:
            assert self._result["avg_stream_start"] == -1
            assert self._result["avg_streaming_time"] == -1
        if self._expected_speech is not None:
            assert self._tester._latest_response["output"]["utterance"] == self._expected_speech

    def then_listener_stops_without_reading_stream_text(self):
        assert self._listener.stop_count == 1
        assert self._listener.read_count == 0
        assert self._tester._stream_start_times == [None]
        assert self._tester._stream_end_times == [None]

    def test_expected_speech_still_uses_stream_when_http_utterance_is_empty(self, monkeypatch):
        self.given_silent_semantic_interaction(
            monkeypatch, utterance_state="empty", expected_speech="late streamed speech"
        )
        self.when_interaction_runs()
        self.then_semantic_expectations_pass()
        self.then_listener_stops_after_reading_stream_text()

    def then_listener_stops_after_reading_stream_text(self):
        assert self._listener.read_count == 1
        assert self._listener.stop_count == 1
