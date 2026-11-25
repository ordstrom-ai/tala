from copy import deepcopy
import json
from unittest.mock import Mock

from tala.utils import tdm_client


class TestTDMClientStartIdentity:
    def test_start_session_carries_the_caller_request_id_without_changing_session_data(self, monkeypatch):
        self.given_a_tdm_endpoint_and_start_session_data(monkeypatch)

        self.when_the_identified_start_request_is_sent()

        self.then_the_request_id_is_sent_and_the_session_data_is_unchanged()

    def given_a_tdm_endpoint_and_start_session_data(self, monkeypatch):
        self.session_data = {"device_id": "incremental-contract-test"}
        self.original_session_data = deepcopy(self.session_data)
        response = Mock()
        response.json.return_value = {"session": {"session_id": "handler-session"}}
        self.post = Mock(return_value=response)
        monkeypatch.setattr(tdm_client.requests, "post", self.post)
        self.client = tdm_client.TDMClient("https://handler.example/interact/offer-1")

    def when_the_identified_start_request_is_sent(self):
        self.response = self.client.start_session(self.session_data, request_id="start-request-1")

    def then_the_request_id_is_sent_and_the_session_data_is_unchanged(self):
        request_body = json.loads(self.post.call_args.kwargs["data"])
        assert request_body["request_id"] == "start-request-1"
        assert request_body["request"] == {"start_session": {}}
        assert request_body["session"] == self.original_session_data
        assert self.session_data == self.original_session_data
        assert self.response["session"]["session_id"] == "handler-session"

    def test_incremental_session_start_carries_an_explicit_opt_in(self, monkeypatch):
        self.given_a_tdm_endpoint_and_start_session_data(monkeypatch)

        self.when_an_incremental_session_is_started()

        self.then_only_the_incremental_start_has_an_opt_in_parameter()

    def when_an_incremental_session_is_started(self):
        self.response = self.client.start_session(
            self.session_data, request_id="start-request-1", incremental_input=True
        )

    def then_only_the_incremental_start_has_an_opt_in_parameter(self):
        request_body = json.loads(self.post.call_args.kwargs["data"])
        assert request_body["request"] == {"start_session": {"incremental_input": True}}
        assert request_body["request_id"] == "start-request-1"
        assert self.session_data == self.original_session_data

    def test_ordinary_session_start_preserves_the_original_wire_payload(self, monkeypatch):
        self.given_a_tdm_endpoint_and_start_session_data(monkeypatch)

        self.when_an_ordinary_session_is_started()

        self.then_no_incremental_start_metadata_is_added()

    def when_an_ordinary_session_is_started(self):
        self.response = self.client.start_session(self.session_data)

    def then_no_incremental_start_metadata_is_added(self):
        request_body = json.loads(self.post.call_args.kwargs["data"])
        assert request_body == {
            "version": tdm_client.PROTOCOL_VERSION,
            "session": self.original_session_data,
            "request": {
                "start_session": {}
            },
        }
