from threading import Event
from unittest.mock import Mock

import pytest

from tala.utils import requestor


class TestRequestorBaseClass:
    def given_gpt_request(
        self,
        messages=None,
        use_json=True,
        model=requestor.DEFAULT_GPT_MODEL,
        reasoning_effort=None,
        allow_caching=True,
        default_gpt_response="[]",
        response_format=None,
        allow_json_repair=True,
    ):
        msgs = messages if messages else []
        request_id = "some-request-id"
        self._gpt_request = requestor.GPTRequest(
            messages=msgs,
            use_json=use_json,
            request_id=request_id,
            model=model,
            reasoning_effort=reasoning_effort,
            allow_caching=allow_caching,
            default_gpt_response=default_gpt_response,
            response_format=response_format,
            allow_json_repair=allow_json_repair,
        )

    def when_request_is_made(self):
        self._gpt_request.make()

    def _then_request_is_done(self):
        self._gpt_request._done.wait(timeout=1)
        assert self._gpt_request._done.is_set()


class TestMakeRequest(TestRequestorBaseClass):
    @classmethod
    def setup_class(cls):
        def make_request(*args):
            return args

        cls._original_make_request = requestor.make_request
        requestor.make_request = make_request
        requestor.REQUESTOR_URL = "URL-FOR-REQUESTOR"
        requestor.REQUESTOR_BASE_URL = "BASE-URL-FOR-REQUESTOR"

    @classmethod
    def teardown_class(cls):
        requestor.make_request = cls._original_make_request

    def test_basic_call(self):
        self.given_gpt_request([{
            "role": "system",
            "content": "you are a JSON creator. You get descriptions of JSON structures in NL, and you create the JSON."
        }, {
            "role": "user",
            "content": "i want keys 1 2 3 with values a b c"
        }])
        self.when_request_is_made()
        self.then_request_call_is_done_with_response((
            'URL-FOR-REQUESTOR', {
                'gpt_request': {
                    'allow_caching': True,
                    'messages': [{
                        'role': 'system',
                        'content': 'you are a JSON creator. You get descriptions of JSON structures in NL, and you create the JSON.'
                    }, {
                        'role': 'user',
                        'content': 'i want keys 1 2 3 with values a b c'
                    }],
                    'temperature': 0.1,
                    'max_tokens': 50,
                    'max_retries': 0,
                    'stop': [],
                    'default_gpt_response': '[]',
                    'use_json': True,
                    'model': 'gpt-4o-2024-11-20',
                    'reasoning_effort': None,
                },
                'priority': 10,
                'request_id': 'some-request-id'
            }
        ))

    def test_structured_response_format_is_forwarded(self):
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "test_schema",
                "strict": True,
                "schema": {
                    "type": "object"
                }
            },
        }
        self.given_gpt_request(response_format=response_format)

        self.when_request_is_made()

        self.then_response_format_is_forwarded(response_format)

    def then_response_format_is_forwarded(self, response_format):
        self._then_request_is_done()
        request_payload = self._gpt_request._response[1]["gpt_request"]
        assert request_payload["response_format"] == response_format

    def test_structured_request_can_disable_json_repair(self):
        self.given_gpt_request(
            use_json=True,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "test"
                }
            },
            allow_json_repair=False,
        )
        self.given_invalid_json_response()

        self.when_structured_json_response_is_read()

        self.then_structured_decoding_error_is_reported()

    def given_invalid_json_response(self):
        self._gpt_request._response = {"response_body": "not JSON"}
        self._gpt_request._done.set()

    def when_structured_json_response_is_read(self):
        try:
            self._gpt_request.json_response
        except requestor.GPTStructuredOutputError as error:
            self._decoding_error = error

    def then_structured_decoding_error_is_reported(self):
        assert self._decoding_error.request_id == "some-request-id"
        assert not self._gpt_request._json_repair_attempted

    def then_request_call_is_done_with_response(self, expected_response):
        self._then_request_is_done()
        self.then_request_call_has_response(expected_response)

    def then_request_call_has_response(self, expected_response):
        response = self._gpt_request._response[0:2]
        assert response == expected_response, f'Expected "{expected_response}", got "{response}"'

    def test_call_with_added_messages_for_all_three_roles(self):
        self.given_gpt_request()
        self.given_system_message(
            'you are a JSON creator. You get descriptions of JSON structures in NL, and you create the JSON.'
        )
        self.given_user_message('i want keys 1 2 3 with values a b c')
        self.given_assistant_message('you wanted keys 1 2 3 with values a b c')
        self.when_request_is_made()
        self.then_request_call_is_done_with_response((
            'URL-FOR-REQUESTOR', {
                'gpt_request': {
                    'allow_caching': True,
                    'messages': [{
                        'role': 'system',
                        'content': 'you are a JSON creator. You get descriptions of JSON structures in NL, and you create the JSON.'
                    }, {
                        'role': 'user',
                        'content': 'i want keys 1 2 3 with values a b c'
                    }, {
                        'role': 'assistant',
                        'content': 'you wanted keys 1 2 3 with values a b c'
                    }],
                    'temperature': 0.1,
                    'max_tokens': 50,
                    'max_retries': 0,
                    'stop': [],
                    'default_gpt_response': '[]',
                    'use_json': True,
                    'model': 'gpt-4o-2024-11-20',
                    'reasoning_effort': None,
                },
                'priority': 10,
                'request_id': 'some-request-id'
            }
        ))

    def given_system_message(self, message):
        self._gpt_request.add_system_message(message)

    def given_user_message(self, message):
        self._gpt_request.add_user_message(message)

    def given_assistant_message(self, message):
        self._gpt_request.add_assistant_message(message)

    def test_call_using_text(self):
        self.given_gpt_request(use_json=False)
        self.given_system_message('you say hey to mom')
        self.given_user_message('say hey to mom')
        self.when_request_is_made()
        self.then_request_call_is_done_with_response((
            'URL-FOR-REQUESTOR', {
                'gpt_request': {
                    'allow_caching': True,
                    'messages': [{
                        'role': 'system',
                        'content': 'you say hey to mom'
                    }, {
                        'role': 'user',
                        'content': 'say hey to mom'
                    }],
                    'temperature': 0.1,
                    'max_tokens': 50,
                    'max_retries': 0,
                    'stop': [],
                    'default_gpt_response': '[]',
                    'use_json': False,
                    'model': 'gpt-4o-2024-11-20',
                    'reasoning_effort': None,
                },
                'priority': 10,
                'request_id': 'some-request-id'
            }
        ))

    def test_add_messages(self):
        self.given_gpt_request(use_json=False)
        self.given_messages([{
            'role': 'system',
            'content': 'you say hey to mom'
        }, {
            'role': 'user',
            'content': 'say hey to mom'
        }])
        self.when_request_is_made()
        self.then_request_call_is_done_with_response((
            'URL-FOR-REQUESTOR', {
                'gpt_request': {
                    'allow_caching': True,
                    'messages': [{
                        'role': 'system',
                        'content': 'you say hey to mom'
                    }, {
                        'role': 'user',
                        'content': 'say hey to mom'
                    }],
                    'temperature': 0.1,
                    'max_tokens': 50,
                    'max_retries': 0,
                    'stop': [],
                    'default_gpt_response': '[]',
                    'use_json': False,
                    'model': 'gpt-4o-2024-11-20',
                    'reasoning_effort': None,
                },
                'priority': 10,
                'request_id': 'some-request-id'
            }
        ))

    def given_messages(self, messages):
        self._gpt_request.add_messages(messages)

    def test_get_json_response(self):
        self.given_gpt_request(use_json=True)
        self.given_request_was_made()
        self.when_response_is({"response_body": '{"JSON": true}'})
        self.then_json_response_is({"JSON": True})

    def given_request_was_made(self):
        self._gpt_request.make()

    def when_response_is(self, response):
        self._then_request_is_done()
        self._gpt_request._response = response

    def then_json_response_is(self, expected_response):
        self._then_request_is_done()
        assert self._gpt_request.json_response == expected_response, f'Expected "{expected_response}", got "{self._gpt_request.json_response}"'

    def test_get_text_response_unquotes(self):
        self.given_gpt_request(use_json=False)
        self.given_request_was_made()
        self.when_response_is({"response_body": '"This is not JSON"'})
        self.then_text_response_is("This is not JSON")

    def then_text_response_is(self, expected_response):
        self._then_request_is_done()
        assert self._gpt_request.text_response == expected_response, f'Expected "{expected_response}", got "{self._gpt_request.text_response}"'

    def test_reasoning_effort(self):
        self.given_gpt_request(
            messages=[{
                "role": "system",
                "content": "you are a JSON creator. You get descriptions of JSON structures in NL, and you create the JSON."
            }, {
                "role": "user",
                "content": "i want keys 1 2 3 with values a b c"
            }],
            model='gpt-5.1-2025-11-13',
            reasoning_effort='low',
        )
        self.when_request_is_made()
        self.then_request_call_is_done_with_response((
            'URL-FOR-REQUESTOR', {
                'gpt_request': {
                    'allow_caching': True,
                    'messages': [{
                        'role': 'system',
                        'content': 'you are a JSON creator. You get descriptions of JSON structures in NL, and you create the JSON.'
                    }, {
                        'role': 'user',
                        'content': 'i want keys 1 2 3 with values a b c'
                    }],
                    'temperature': 0.1,
                    'max_tokens': 50,
                    'max_retries': 0,
                    'stop': [],
                    'default_gpt_response': '[]',
                    'use_json': True,
                    'model': 'gpt-5.1-2025-11-13',
                    'reasoning_effort': 'low',
                },
                'priority': 10,
                'request_id': 'some-request-id'
            }
        ))

    def test_no_cache(self):
        self.given_gpt_request(
            messages=[{
                "role": "system",
                "content": "you are a JSON creator. You get descriptions of JSON structures in NL, and you create the JSON."
            }, {
                "role": "user",
                "content": "i want keys 1 2 3 with values a b c"
            }],
            model='gpt-5.1-2025-11-13',
            allow_caching=False,
        )
        self.when_request_is_made()
        self.then_request_call_is_done_with_response((
            'URL-FOR-REQUESTOR', {
                'gpt_request': {
                    'allow_caching': False,
                    'messages': [{
                        'role': 'system',
                        'content': 'you are a JSON creator. You get descriptions of JSON structures in NL, and you create the JSON.'
                    }, {
                        'role': 'user',
                        'content': 'i want keys 1 2 3 with values a b c'
                    }],
                    'temperature': 0.1,
                    'max_tokens': 50,
                    'max_retries': 0,
                    'stop': [],
                    'default_gpt_response': '[]',
                    'use_json': True,
                    'model': 'gpt-5.1-2025-11-13',
                    'reasoning_effort': None,
                },
                'priority': 10,
                'request_id': 'some-request-id'
            }
        ))

    def test_retrying_means_double_tokens(self):
        self.given_gpt_request([{
            "role": "system",
            "content": "you are a JSON creator. You get descriptions of JSON structures in NL, and you create the JSON."
        }, {
            "role": "user",
            "content": "i want keys 1 2 3 with values a b c"
        }])
        self.given_request_is_made()
        self.when_updating_request_with_latest_messages()
        self.then_max_tokens_is(100)

    def test_dynamic_read_timeout_updates_with_tokens(self):
        self.given_gpt_request()
        initial_timeout = self._gpt_request._read_timeout
        self.given_request_is_made()
        self.when_updating_request_with_latest_messages()
        assert self._gpt_request._read_timeout > initial_timeout

    def given_request_is_made(self):
        self._gpt_request.make()
        self._gpt_request._response = {"response_body": "mock-response-body"}

    def when_updating_request_with_latest_messages(self):
        self._gpt_request.update_with_last_assistant_and_next_user_message("another line")

    def then_max_tokens_is(self, expected_max_tokens):
        assert self._gpt_request.max_tokens == expected_max_tokens

    def test_assign_deployment_request(self):
        self.given_deployment_assignment_request()
        self.when_request_is_made()
        self.then_request_call_is_done_with_response((
            'BASE-URL-FOR-REQUESTOR/assign-deployment', {
                'gpt_request': {
                    'allow_caching': True,
                    'messages': [],
                    'temperature': 0.1,
                    'max_tokens': 50,
                    'max_retries': 0,
                    'stop': [],
                    'default_gpt_response': '[]',
                    'use_json': True,
                    'model': 'gpt-4o-2024-11-20',
                    'reasoning_effort': None,
                },
                'priority': 10,
                'request_id': 'some-request-id'
            }
        ))

    def given_deployment_assignment_request(
        self,
        messages=None,
        use_json=True,
        model=requestor.DEFAULT_GPT_MODEL,
        reasoning_effort=None,
        allow_caching=True
    ):
        msgs = messages if messages else []
        request_id = "some-request-id"
        self._gpt_request = requestor.GPTRequestForDeploymentAssignment(
            messages=msgs,
            use_json=use_json,
            request_id=request_id,
            model=model,
            reasoning_effort=reasoning_effort,
            allow_caching=allow_caching
        )

    def test_update_tpm_request(self):
        self.given_update_tpm_request()
        self.when_request_is_made()
        self.when_update_tpm_request_finishes()
        self.then_request_call_has_response((
            'BASE-URL-FOR-REQUESTOR/update-tpm', {
                'deployment_name': 'some-deployment-name',
                'deployment_resource': 'some-deployment-resource',
                'request_id': 'some-update-id',
                'total_tokens_used': 666,
            }
        ))

    def given_update_tpm_request(self):
        self._update_tpm_completed = Event()
        completion_logger = Mock()

        def record_completion(event, **_fields):
            if event == "received response":
                self._update_tpm_completed.set()

        completion_logger.info.side_effect = record_completion
        self._gpt_request = requestor.UpdateTPMRequest(
            request_id="some-update-id",
            deployment_name="some-deployment-name",
            deployment_resource="some-deployment-resource",
            total_tokens_used=666,
            logger=completion_logger,
        )

    def when_update_tpm_request_finishes(self):
        assert self._update_tpm_completed.wait(timeout=1), "UpdateTPMRequest did not publish its response"


class RequestorResponse(TestRequestorBaseClass):
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        if 400 <= self.status_code < 500:
            raise Exception(f"{self.status_code} Client error")
        if 500 <= self.status_code < 600:
            raise Exception(f"{self.status_code} Server error")


class TestResponses(TestRequestorBaseClass):
    @classmethod
    def setup_class(cls):
        cls._original_post_request = requestor.requests_session.post
        requestor.REQUESTOR_URL = "URL-FOR-REQUESTOR"
        requestor.REQUESTOR_BASE_URL = "BASE-URL-FOR-REQUESTOR"

    @classmethod
    def teardown_class(cls):
        requestor.requests_session.post = cls._original_post_request

    def setup_method(self):
        def mocked_requests_session_post(*args, **kwargs):
            if self._requests_session_responses:
                return self._requests_session_responses.pop(0)
            assert self._requests_session_response is not None, ("A requests_session response was not set in the test")
            return self._requests_session_response

        requestor.requests_session.post = mocked_requests_session_post  # pyright: ignore[reportAttributeAccessIssue]
        self._requests_session_response = None
        self._requests_session_responses = []

    def test_success_response_returns_json_response(self):
        self.given_gpt_request(
            [{
                "role": "system",
                "content": "you are a JSON creator. You get descriptions of JSON structures in NL, and you create the JSON."
            }, {
                "role": "user",
                "content": "i want keys 1 2 3 with values a b c"
            }],
            use_json=True,
            default_gpt_response="{\"default\": \"response\"}",
        )
        self.given_mocked_requestor_response(
            body={
                "status": "success",
                "response_body": "{\"1\": \"a\", \"2\": \"b\", \"3\": \"c\"}",
                "deployment": "some-deployment",
                "gpt_time_consumption": 1.25,
                "request_id": "some-id",
            },
            status_code=200,
        )
        self.when_request_is_made()
        self.then_json_response_is({"1": "a", "2": "b", "3": "c"})

    @pytest.mark.parametrize("completion_status", ["completed", "truncated", "refused", "error"])
    def test_completion_status_is_exposed(self, completion_status):
        self.given_gpt_request(response_format={"type": "json_schema", "json_schema": {"name": "test"}})
        self.given_mocked_requestor_response(
            body={
                "status": "success",
                "response_body": "{}" if completion_status == "completed" else None,
                "completion_status": completion_status,
                "deployment": "some-deployment",
                "gpt_time_consumption": 1.25,
                "request_id": "some-id",
            },
            status_code=200,
        )

        self.when_request_is_made()

        self.then_completion_status_is(completion_status)

    def test_legacy_success_response_is_completed(self):
        self.given_gpt_request()
        self.given_mocked_requestor_response(
            body={
                "status": "success",
                "response_body": "{}",
                "deployment": "some-deployment",
                "gpt_time_consumption": 1.25,
                "request_id": "some-id",
            },
            status_code=200,
        )

        self.when_request_is_made()

        self.then_completion_status_is("completed")

    def then_completion_status_is(self, expected_status):
        assert self._gpt_request.completion_status == expected_status

    def given_mocked_requestor_response(self, status_code, body):
        self._requests_session_response = RequestorResponse(status_code, body)

    def given_mocked_requestor_responses(self, responses):
        self._requests_session_responses = [RequestorResponse(status, body) for status, body in responses]

    def then_json_response_is(self, expected_response):
        self._then_request_is_done()
        assert expected_response == self._gpt_request.json_response

    def test_success_response_returns_str_response(self):
        self.given_gpt_request(
            [{
                "role": "system",
                "content": "you are an expert in completing sentences which refer to pop culture"
            }, {
                "role": "user",
                "content": "Nobody expects..."
            }],
            use_json=False,
            default_gpt_response="a default response message! Something went wrong!",
        )
        self.given_mocked_requestor_response(
            body={
                "status": "success",
                "response_body": "the Spanish Inquisition!",
                "deployment": "some-deployment",
                "gpt_time_consumption": 1.25,
                "request_id": "some-id",
            },
            status_code=200,
        )
        self.when_request_is_made()
        self.then_str_response_is("the Spanish Inquisition!")

    def then_str_response_is(self, expected_response):
        self._then_request_is_done()
        assert expected_response == self._gpt_request.response

    def test_failure_response_returns_default_json_response(self):
        self.given_gpt_request(
            [{
                "role": "system",
                "content": "you are a JSON creator. You get descriptions of JSON structures in NL, and you create the JSON."
            }, {
                "role": "user",
                "content": "i want keys 1 2 3 with values a b c"
            }],
            use_json=True,
            default_gpt_response="{\"default\": \"response\"}",
        )
        self.given_mocked_requestor_response(
            body={
                "status": "failure",
                "gpt_time_consumption": -1,
                "request_id": "some-id",
                "failure_message": "an error message",
            },
            status_code=500,
        )
        self.when_request_is_made()
        self.then_json_response_is({"default": "response"})

    def test_failure_response_returns_default_str_response(self):
        self.given_gpt_request(
            [{
                "role": "system",
                "content": "you are an expert in completing sentences which refer to pop culture"
            }, {
                "role": "user",
                "content": "Nobody expects..."
            }],
            use_json=False,
            default_gpt_response="a default response message! Something went wrong!",
        )
        self.given_mocked_requestor_response(
            body={
                "status": "failure",
                "gpt_time_consumption": -1,
                "request_id": "some-id",
                "failure_message": "an error message",
            },
            status_code=500,
        )
        self.when_request_is_made()
        self.then_str_response_is("a default response message! Something went wrong!")

    def test_invalid_json_response_is_repaired(self):
        self.given_gpt_request(
            [{
                "role": "system",
                "content": "you are a JSON creator. You get descriptions of JSON structures in NL, and you create the JSON."
            }, {
                "role": "user",
                "content": "i want keys 1 2 3 with values a b c"
            }],
            use_json=True,
            default_gpt_response="{\"default\": \"response\"}",
        )
        self.given_mocked_requestor_responses([
            (
                200, {
                    "status": "success",
                    "response_body": '{"body": ["incomplete"',
                    "deployment": "some-deployment",
                    "gpt_time_consumption": 1.25,
                    "request_id": "some-id",
                }
            ),
            (
                200, {
                    "status": "success",
                    "response_body": '{"body": ["complete"]}',
                    "deployment": "some-deployment",
                    "gpt_time_consumption": 1.25,
                    "request_id": "some-id-2",
                }
            ),
        ])
        self.when_request_is_made()
        self.then_json_response_is({"body": ["complete"]})

    def test_content_filter_response_raises(self):
        self.given_gpt_request(
            [{
                "role": "system",
                "content": "you are a JSON creator. You get descriptions of JSON structures in NL, and you create the JSON."
            }, {
                "role": "user",
                "content": "i want keys 1 2 3 with values a b c"
            }],
            use_json=True,
            default_gpt_response="{\"default\": \"response\"}",
        )
        self.given_mocked_requestor_response(
            body={
                "error": {
                    "message": "The response was filtered due to content policy.",
                    "param": "prompt",
                    "code": "content_filter",
                    "status": 400,
                    "innererror": {
                        "code": "ResponsibleAIPolicyViolation",
                        "content_filter_result": {
                            "jailbreak": {
                                "detected": True,
                                "filtered": True
                            }
                        },
                    },
                },
            },
            status_code=200,
        )
        self.when_request_is_made()
        with pytest.raises(requestor.GPTContentFilterError):
            _ = self._gpt_request.json_response

    def test_non_filter_error_returns_default_json(self):
        self.given_gpt_request(
            [{
                "role": "system",
                "content": "you are a JSON creator. You get descriptions of JSON structures in NL, and you create the JSON."
            }, {
                "role": "user",
                "content": "i want keys 1 2 3 with values a b c"
            }],
            use_json=True,
            default_gpt_response="{\"default\": \"response\"}",
        )
        self.given_mocked_requestor_response(
            body={"error": {
                "message": "Bad request",
                "code": "invalid_request",
            }},
            status_code=200,
        )
        self.when_request_is_made()
        self.then_json_response_is({"default": "response"})
