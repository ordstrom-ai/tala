from copy import deepcopy
import time
import uuid
from typing import Mapping, Sequence

from tala.model.input_hypothesis import InputHypothesis
from tala.utils.tdm_client import InvalidResponseError, PROTOCOL_VERSION, TDMClient, TDMRuntimeException

HYPOTHESES_UPDATED = "input.utterance.hypotheses.updated"
UTTERANCE_FINALIZED = "input.utterance.finalized"


class IncrementalTDMClient:
    """Send hypothesis revisions and finalization in an explicitly opted-in TDM session."""
    def __init__(self, tdm_client: TDMClient):
        self._tdm_client = tdm_client
        self._session = tdm_client.session
        self._utterance_id = str(uuid.uuid4())
        self._sequence = 0
        self._finalized = False
        self._event_history = []

    @property
    def session(self):
        return self._session

    @property
    def event_history(self):
        return deepcopy(self._event_history)

    def submit_hypotheses(self, hypotheses: Sequence[InputHypothesis], session: Mapping = None) -> Mapping:
        return self._submit_event(HYPOTHESES_UPDATED, hypotheses, session)

    def finalize_utterance(self, hypotheses: Sequence[InputHypothesis], session: Mapping = None) -> Mapping:
        acknowledgement = self._submit_event(UTTERANCE_FINALIZED, hypotheses, session)
        self._finalized = True
        return acknowledgement

    def _submit_event(self, event_type, hypotheses, session):
        if self._finalized:
            raise TDMRuntimeException("The utterance is already finalized.")

        hypothesis_payload = _hypotheses_as_json(hypotheses)
        current_session = self._session if session is None else session
        if current_session is None:
            raise TDMRuntimeException("Start a TDM session before sending utterance events.")

        self._sequence += 1
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "utterance_id": self._utterance_id,
            "revision_id": str(uuid.uuid4()),
            "sequence": self._sequence,
            "hypotheses": hypothesis_payload,
        }
        request = {
            "version": PROTOCOL_VERSION,
            "session": current_session,
            "request": {
                "utterance_event": event,
            },
        }

        started = time.perf_counter()
        response = self._tdm_client.make_request(request)
        elapsed_seconds = time.perf_counter() - started
        acknowledgement, self._session = _validate_event_acknowledgement(response, event)
        self._event_history.append({
            "event_id": event["event_id"],
            "event_type": event_type,
            "revision_id": event["revision_id"],
            "sequence": event["sequence"],
            "elapsed_seconds": elapsed_seconds,
            "acknowledgement": deepcopy(acknowledgement),
        })
        return acknowledgement


def _hypotheses_as_json(hypotheses):
    try:
        hypothesis_payload = [hypothesis.as_dict() for hypothesis in hypotheses]
    except (AttributeError, TypeError) as error:
        raise ValueError("Incremental speech revisions must be sequences of InputHypothesis values.") from error
    if not hypothesis_payload:
        raise ValueError("Incremental speech revisions must include at least one hypothesis.")
    return hypothesis_payload


def _validate_event_acknowledgement(response, event):
    try:
        acknowledgement = response["utterance_event"]
        session = response["session"]
        session["offer_id"]
        session["session_id"]
        expected_utterance_status = "finalized" if event["event_type"] == UTTERANCE_FINALIZED else "open"
        if acknowledgement["turn_status"] != "open" or \
                acknowledgement["utterance_status"] != expected_utterance_status:
            raise ValueError("Pipeline returned an unexpected utterance-event status.")
        for field in (
            "event_id",
            "event_type",
            "utterance_id",
            "revision_id",
            "sequence",
        ):
            if acknowledgement[field] != event[field]:
                raise ValueError("Pipeline acknowledged a different utterance event.")
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidResponseError("Pipeline returned an invalid utterance-event acknowledgement.") from error
    return acknowledgement, session
