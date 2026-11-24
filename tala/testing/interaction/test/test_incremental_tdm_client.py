from copy import deepcopy

from tala.model.input_hypothesis import InputHypothesis
from tala.testing.interaction.incremental_tdm_client import IncrementalTDMClient
from tala.utils.tdm_client import InvalidResponseError, PROTOCOL_VERSION, TDMRuntimeException


class TestIncrementalTDMClient:
    def test_revisions_share_an_utterance_and_final_event_advances_the_sequence(self):
        self.given_a_tdm_client_and_two_hypothesis_revisions()

        self.when_the_interim_and_final_events_are_submitted()

        self.then_the_events_are_ordered_and_acknowledged()

    def test_no_more_events_are_accepted_after_finalization(self):
        self.given_a_tdm_client_and_two_hypothesis_revisions()
        self.when_the_final_event_is_submitted()

        self.when_an_interim_event_is_submitted_after_finalization()

        self.then_the_finalized_utterance_rejects_further_updates()

    def test_mismatched_event_acknowledgement_is_rejected(self):
        self.given_a_tdm_client_with_a_mismatched_acknowledgement()

        self.when_the_interim_event_is_submitted()

        self.then_the_invalid_acknowledgement_is_rejected()

    def given_a_tdm_client_and_two_hypothesis_revisions(self):
        self.initial_session = {"session_id": "session-1", "offer_id": "offer-1"}
        self.tdm_client = FakeTDMClient(self.initial_session)
        self.client = IncrementalTDMClient(self.tdm_client)
        self.interim_hypotheses = [InputHypothesis("Turn", 0.72)]
        self.final_hypotheses = [InputHypothesis("Turn left at the next street.", 0.97)]

    def given_a_tdm_client_with_a_mismatched_acknowledgement(self):
        self.given_a_tdm_client_and_two_hypothesis_revisions()
        self.tdm_client.mismatch_next_event_id = True

    def when_the_interim_and_final_events_are_submitted(self):
        self.interim_acknowledgement = self.client.submit_hypotheses(
            self.interim_hypotheses,
            self.initial_session,
        )
        self.final_acknowledgement = self.client.finalize_utterance(self.final_hypotheses)

    def when_the_final_event_is_submitted(self):
        self.client.finalize_utterance(self.final_hypotheses, self.initial_session)

    def when_an_interim_event_is_submitted_after_finalization(self):
        self.event_error = None
        try:
            self.client.submit_hypotheses(self.interim_hypotheses)
        except TDMRuntimeException as error:
            self.event_error = error

    def when_the_interim_event_is_submitted(self):
        self.event_error = None
        try:
            self.client.submit_hypotheses(self.interim_hypotheses, self.initial_session)
        except InvalidResponseError as error:
            self.event_error = error

    def then_the_events_are_ordered_and_acknowledged(self):
        interim_event = self.tdm_client.requests[0]["request"]["utterance_event"]
        final_event = self.tdm_client.requests[1]["request"]["utterance_event"]
        assert interim_event["event_type"] == "input.utterance.hypotheses.updated"
        assert final_event["event_type"] == "input.utterance.finalized"
        assert interim_event["utterance_id"] == final_event["utterance_id"]
        assert [interim_event["sequence"], final_event["sequence"]] == [1, 2]
        assert interim_event["event_id"] != final_event["event_id"]
        assert self.tdm_client.requests[0]["version"] == PROTOCOL_VERSION
        assert self.tdm_client.requests[1]["session"]["request_id"] == "event-1"
        assert self.interim_acknowledgement["event_id"] == interim_event["event_id"]
        assert self.final_acknowledgement["event_id"] == final_event["event_id"]
        assert [event["sequence"] for event in self.client.event_history] == [1, 2]
        assert "hypotheses" not in self.client.event_history[0]

    def then_the_finalized_utterance_rejects_further_updates(self):
        assert self.event_error is not None
        assert self.event_error.args == ("The utterance is already finalized.", )
        assert len(self.tdm_client.requests) == 1

    def then_the_invalid_acknowledgement_is_rejected(self):
        assert self.event_error is not None
        assert self.event_error.args == ("Pipeline returned an invalid utterance-event acknowledgement.", )


class FakeTDMClient:
    def __init__(self, session):
        self.session = deepcopy(session)
        self.requests = []
        self.mismatch_next_event_id = False

    def make_request(self, request):
        self.requests.append(deepcopy(request))
        event = request["request"]["utterance_event"]
        response_session = deepcopy(request["session"])
        response_session["request_id"] = f"event-{event['sequence']}"
        event_id = "wrong-event" if self.mismatch_next_event_id else event["event_id"]
        self.mismatch_next_event_id = False
        return {
            "session": response_session,
            "utterance_event": {
                "event_id": event_id,
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
