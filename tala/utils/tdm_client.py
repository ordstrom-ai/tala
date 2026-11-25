import json
import os
from typing import Sequence, Mapping  # noqa: F401

import requests

from tala.model.input_hypothesis import InputHypothesis  # noqa: F401
from tala.model.interpretation import Interpretation  # noqa: F401
from tala.model.event_notification import EventNotification  # noqa: F401
from tala.utils.await_endpoint import await_endpoint
from tala.utils.observable import Observable

PROTOCOL_VERSION = "3.4"


class InvalidResponseError(Exception):
    pass


class TDMRuntimeException(Exception):
    pass


class TDMClient(Observable):
    def __init__(self, url: str) -> None:
        super(TDMClient, self).__init__()
        self._url = url
        self._session = None
        self._request_timeout = self._get_request_timeout()

    @property
    def session(self):
        return self._session

    def wait_to_start(self, timeout=3):
        url = self._url.replace("/interact", "/health")
        await_endpoint(url, timeout)

    def request_text_input(self, utterance: str, session: Mapping = None) -> Mapping:
        def _create_text_input_request(session, utterance):
            return {
                "version": PROTOCOL_VERSION,
                "session": session,
                "request": {
                    "natural_language_input": {
                        "modality": "text",
                        "utterance": utterance,
                    }
                }
            }

        session = session if session else self.session
        request = _create_text_input_request(session, utterance)
        response = self._make_request(request)
        return response

    def request_speech_input(self, hypotheses: Sequence[InputHypothesis], session: Mapping = None) -> Mapping:
        def _create_speech_input_request(session, hypotheses):
            return {
                "version": PROTOCOL_VERSION,
                "session": session,
                "request": {
                    "natural_language_input": {
                        "modality": "speech",
                        "hypotheses": [{
                            "utterance": hypothesis.utterance,
                            "confidence": hypothesis.confidence,
                        } for hypothesis in hypotheses],
                    }
                }
            }  # yapf: disable

        session = session if session else self.session
        request = _create_speech_input_request(session, hypotheses)
        response = self._make_request(request)
        return response

    def request_semantic_input(
        self, interpretations: Sequence[Interpretation], session: Mapping = None, entities: Sequence = None
    ) -> Mapping:
        def _create_semantic_input_request(session, interpretations, entities):
            if entities is None:
                entities = []
            return {
                "version": PROTOCOL_VERSION,
                "session": session,
                "request": {
                    "semantic_input": {
                        "interpretations": [interpretation.as_dict() for interpretation in interpretations],
                        "entities": entities,
                    }
                }
            }  # yapf: disable

        session = session if session else self.session
        request = _create_semantic_input_request(session, interpretations, entities)
        response = self._make_request(request)
        return response

    def request_passivity(self, session: Mapping = None) -> Mapping:
        request = {"version": PROTOCOL_VERSION, "session": session, "request": {"passivity": {}}}
        response = self._make_request(request)
        return response

    def start_session(
        self, session_data: Mapping = None, *, request_id: str = None, incremental_input: bool = False
    ) -> Mapping:
        session_object = session_data or {}
        request = {"version": PROTOCOL_VERSION, "session": session_object, "request": {"start_session": {}}}
        if incremental_input:
            request["request"]["start_session"]["incremental_input"] = True
        if request_id is not None:
            request["request_id"] = request_id
        response = self._make_request(request)
        return response

    def make_request(self, *args, **kwargs):
        return self._make_request(*args, **kwargs)

    def _make_request(self, request_body):
        data_as_json = json.dumps(request_body)
        headers = {'Content-type': 'application/json'}
        response_object = requests.post(
            self._url,
            data=data_as_json,
            headers=headers,
            timeout=self._request_timeout,
        )
        response_object.raise_for_status()
        try:
            response = response_object.json()
        except ValueError:
            raise InvalidResponseError(f"Expected a valid JSON response but got '{response_object}'.")

        if "error" in response:
            description = response["error"]["description"]
            raise TDMRuntimeException(description)
        return response

    def _get_request_timeout(self):
        timeout = os.getenv("TDM_REQUEST_TIMEOUT_SECONDS", "120")
        try:
            return float(timeout)
        except ValueError:
            return 120.0
