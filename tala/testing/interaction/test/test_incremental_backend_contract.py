from copy import deepcopy
import importlib
import importlib.util
import json as json_module
import os
from pathlib import Path
import sys
from urllib.parse import unquote, urlparse

from cryptography.fernet import Fernet
import pytest
import requests

from tala.nlg import nlg
from tala.testing.interaction.interaction_tester import InteractionTester

HANDLER_SOURCE_ENV = "TALA_INCREMENTAL_HANDLER_SOURCE"
PIPELINE_SOURCE_ENV = "TALA_INCREMENTAL_PIPELINE_SOURCE"
FUNCTION_KEY = "incremental-contract-test-key"


class TestIncrementalBackendContract:
    def test_scripted_turn_uses_handler_and_pipeline_with_stubbed_downstreams(self, monkeypatch, request):
        self.given_local_backend_sources_are_available(monkeypatch, request)
        self.given_local_backend_dependencies_are_stubbed(monkeypatch)

        self.when_one_scripted_incremental_turn_runs()

        self.then_final_hypothesis_uses_cached_nlu_in_one_completed_pipeline_turn()

    def given_local_backend_sources_are_available(self, monkeypatch, request):
        handler_source = os.environ.get(HANDLER_SOURCE_ENV)
        pipeline_source = os.environ.get(PIPELINE_SOURCE_ENV)
        if not handler_source or not pipeline_source:
            pytest.skip(f"Set {HANDLER_SOURCE_ENV} and {PIPELINE_SOURCE_ENV} to run the local backend contract test.")

        self.handler_source = Path(handler_source).expanduser().resolve()
        self.pipeline_source = Path(pipeline_source).expanduser().resolve()
        if not (self.handler_source / "function_app.py").is_file() or \
                not (self.pipeline_source / "function_app.py").is_file():
            raise FileNotFoundError("The configured Handler and Pipeline source directories are invalid.")
        if "pipeline" in sys.modules or "src" in sys.modules:
            pytest.skip("Run the local backend contract in isolation; server packages are already imported.")

        initial_module_names = set(sys.modules)
        request.addfinalizer(lambda: self.remove_local_backend_modules(initial_module_names))
        monkeypatch.chdir(self.pipeline_source)
        monkeypatch.syspath_prepend(str(self.handler_source))
        monkeypatch.syspath_prepend(str(self.pipeline_source))
        self.pipeline_core = importlib.import_module("pipeline.core")
        self.pipeline_requests = importlib.import_module("pipeline.requests")
        self.pipeline_store = importlib.import_module("pipeline.input_turn_store")
        self.dashboard_logger = importlib.import_module("dashboard_logger")
        self.pipeline_app = load_python_module(
            "pipeline_function_app_incremental_contract",
            self.pipeline_source / "function_app.py",
        )
        self.handler_serve = importlib.import_module("src.serve")
        self.handler_app = load_python_module(
            "handler_function_app_incremental_contract",
            self.handler_source / "function_app.py",
        )

    @staticmethod
    def remove_local_backend_modules(initial_module_names):
        server_prefixes = ("pipeline", "src")
        for module_name in list(sys.modules):
            is_server_module = any(
                module_name == prefix or module_name.startswith(f"{prefix}.") for prefix in server_prefixes
            )
            is_function_entrypoint = module_name in {
                "handler_function_app_incremental_contract",
                "pipeline_function_app_incremental_contract",
                "dashboard_logger",
            }
            if module_name not in initial_module_names and (is_server_module or is_function_entrypoint):
                del sys.modules[module_name]

    def given_local_backend_dependencies_are_stubbed(self, monkeypatch):
        self.configure_backend_settings(monkeypatch)
        monkeypatch.setattr(
            self.dashboard_logger.DashboardLogger, "send_log_to_data_collection_rule", lambda _self: None
        )
        self.input_turn_store = MemoryInputTurnStore(
            self.pipeline_store.StoredInputTurn,
            self.pipeline_store.InputTurnStoreConflict,
        )
        self.downstream = FakePipelineDownstreams()
        fake_request_handlers = self.create_fake_pipeline_request_handlers()
        monkeypatch.setattr(
            self.pipeline_core.RequestHandlers,
            "default",
            classmethod(lambda _cls: fake_request_handlers),
        )
        monkeypatch.setattr(self.pipeline_app, "input_turn_backend_enabled", lambda: True)
        monkeypatch.setattr(
            self.pipeline_app,
            "create_input_turn_store",
            lambda **_arguments: self.input_turn_store,
        )
        monkeypatch.setattr(
            self.pipeline_requests,
            "make_request_to_nlu",
            self.downstream.make_request_to_nlu,
        )
        monkeypatch.setattr(
            self.pipeline_requests.requests_session,
            "post",
            self.unexpected_pipeline_http_service_call,
        )
        monkeypatch.setattr(
            self.handler_serve,
            "get_offer_from_sanity_storage",
            lambda _offer_id, _logger: deepcopy(self.published_offer),
        )
        monkeypatch.setattr(nlg, "generate", self.downstream.generate_nlg)
        self.http_dispatch = LocalFunctionDispatcher(self.handler_app, self.pipeline_app)
        monkeypatch.setattr(requests, "post", self.http_dispatch.post)

    def configure_backend_settings(self, monkeypatch):
        self.published_offer = {
            "offer_id": "offer-1",
            "ddd": "travel",
            "available_ddds": ["travel"],
            "neural": True,
            "neural_settings": {
                "asr_ndu": False,
                "background_qna_ndg": False,
                "generate_rb_q_feedback_ndg": False,
                "limited_gpt_qna_ndg": False,
                "move_ndu": False,
                "select_comments_neurally": False,
                "word_lookup_ndg": False,
            },
            "nlu": {
                "model_version": "incremental-contract-nlu"
            },
        }
        environment = {
            self.handler_serve.SESSION_ENCRYPTION_KEY_ENV: Fernet.generate_key().decode("utf-8"),
            "INPUT_TURN_CONTEXT_HANDOFF_ENABLED": "true",
            "PIPELINE_INPUT_TURN_ENDPOINT": "https://pipeline.example/api/input-turn/execute",
            "PIPELINE_CONTEXT_COMMIT_ENDPOINT": "https://pipeline.example/api/input-turn/commit-handler-context",
            "PIPELINE_CONTEXT_COMMIT_FUNCTION_KEY": FUNCTION_KEY,
            "PIPELINE_UTTERANCE_EVENT_ENDPOINT": "https://pipeline.example/api/input-turn/utterance-event",
            "INPUT_TURN_BACKEND_ENABLED": "true",
            "ENABLE_QUOTA_CHECKS": "false",
            "FUNCTION_ENDPOINT_DM": "https://dm.example/api/dm",
            "FUNCTION_ENDPOINT_NLU": "https://nlu.example/api/interpret",
            "FUNCTION_ENDPOINT_NDU": "",
            "FUNCTION_ENDPOINT_AB_NDU": "",
            "FUNCTION_ENDPOINT_ASR_NDU": "",
            "FUNCTION_ENDPOINT_NDG": "",
            "FUNCTION_ENDPOINT_NDG_SYSTEM": "",
            "FUNCTION_ENDPOINT_QNA_NDG": "",
            "FUNCTION_ENDPOINT_VOG": "",
            "FUNCTION_ENDPOINT_SECONDARY_NLU": "",
            "FUNCTION_ENDPOINT_NDU_VALIDATION": "",
            "PIPELINE_NLU_DECISION_VALIDATION_MODE": "off",
            "SSE_ENDPOINT": "https://sse.example/event-sse",
            "SSE_BROKER_ENDPOINT_WSS": "wss://sse.example",
        }
        for setting_name, setting_value in environment.items():
            monkeypatch.setenv(setting_name, setting_value)

    def create_fake_pipeline_request_handlers(self):
        return self.pipeline_core.RequestHandlers(
            make_request_to_ndu=self.downstream.unexpected_nlu_downstream_call,
            make_request_to_ab_ndu=self.downstream.unexpected_nlu_downstream_call,
            make_request_to_asr_ndu=self.downstream.unexpected_nlu_downstream_call,
            make_request_to_dm=self.downstream.make_request_to_dm,
            make_request_to_qna_ndg=self.downstream.unexpected_nlu_downstream_call,
            make_request_to_ndg=self.downstream.unexpected_nlu_downstream_call,
            make_request_to_ndg_system=self.downstream.unexpected_nlu_downstream_call,
            make_request_to_nlu=self.downstream.unexpected_nlu_downstream_call,
            make_request=self.downstream.unexpected_nlu_downstream_call,
        )

    @staticmethod
    def unexpected_pipeline_http_service_call(*_args, **_kwargs):
        raise AssertionError("The synthetic dialogue unexpectedly called an HTTP service.")

    def when_one_scripted_incremental_turn_runs(self):
        self.tester = InteractionTester(port=None, use_streaming=False)
        self.response = self.tester.run_testcase(
            {
                "name": "synthetic incremental turn",
                "target_ddd": "travel",
                "url": "https://handler.example/api/interact/offer-1",
                "neural": True,
                "interaction": [{
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
                }, {
                    "speaker": "system",
                    "speech_content": "Destination selected.",
                }],
            },
            offer={"offer_id": "offer-1"},
        )

    def then_final_hypothesis_uses_cached_nlu_in_one_completed_pipeline_turn(self):
        self.assert_scripted_turn_succeeded()
        self.assert_handler_created_the_session_used_by_the_client()
        self.assert_pipeline_processed_and_committed_the_final_turn()
        self.assert_internal_pipeline_requests_use_the_test_function_key()

    def assert_scripted_turn_succeeded(self):
        assert self.response["success"] is True
        assert self.response["transcript"].count("U>") == 1
        assert "Destination selected." in self.response["transcript"]
        event_history = self.response["incremental_event_history"]
        assert [event["event_type"] for event in event_history] == [
            "input.utterance.hypotheses.updated",
            "input.utterance.finalized",
        ]
        assert [event["acknowledgement"]["utterance_status"] for event in event_history] == ["open", "finalized"]

    def assert_handler_created_the_session_used_by_the_client(self):
        start_request = next(
            request for request in self.http_dispatch.frontend_requests if "start_session" in request["body"]["request"]
        )
        event_request = self.http_dispatch.frontend_requests[1]
        assert start_request["body"]["request_id"]
        assert self.response["session_id"] == event_request["body"]["session"]["session_id"]
        assert self.response["session_id"] != start_request["body"]["session"]["session_id"]

    def assert_pipeline_processed_and_committed_the_final_turn(self):
        assert self.downstream.nlu_requests == [{
            "modality": "speech",
            "hypotheses": [{
                "utterance": "Turn",
                "confidence": 0.72
            }],
        }, {
            "modality": "speech",
            "hypotheses": [{
                "utterance": "Turn left at the next street.",
                "confidence": 0.97
            }],
        }]
        assert len(self.downstream.dm_requests) == 2
        final_dm_request = self.downstream.dm_requests[-1]
        assert final_dm_request["request"]["semantic_input"]["interpretations"][0]["utterance"] == \
            "Turn left at the next street."
        session_scope = self.pipeline_store.InputTurnScope("offer-1", self.response["session_id"])
        stored_turn = self.input_turn_store.read(session_scope).payload
        assert stored_turn["status"] == "completed"
        utterance_id = self.response["incremental_event_history"][0]["acknowledgement"]["utterance_id"]
        utterance_record = stored_turn["utterance_input"]["utterances"][utterance_id]
        assert utterance_record["status"] == "finalized"
        assert utterance_record["nlu_attempts"] == 2
        assert utterance_record["nlu_result"]["input_fingerprint"] == \
            utterance_record["revision"]["input_fingerprint"]

    def assert_internal_pipeline_requests_use_the_test_function_key(self):
        assert self.http_dispatch.internal_function_keys
        assert all(key == FUNCTION_KEY for key in self.http_dispatch.internal_function_keys)


def load_python_module(module_name, module_path):
    module_spec = importlib.util.spec_from_file_location(module_name, module_path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"Unable to load Python module at {module_path}.")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    module_spec.loader.exec_module(module)
    return module


class MemoryInputTurnStore:
    def __init__(self, stored_turn_type, conflict_type):
        self._stored_turn_type = stored_turn_type
        self._conflict_type = conflict_type
        self._records = {}
        self._version = 0

    def read(self, scope):
        try:
            version, payload = self._records[scope]
        except KeyError:
            return None
        return self._stored_turn_type(version, deepcopy(payload))

    def create(self, scope, payload):
        if scope in self._records:
            raise self._conflict_type("The session already has an input-turn record.")
        return self._write(scope, payload)

    def replace(self, scope, expected_version, payload):
        try:
            version, _ = self._records[scope]
        except KeyError as error:
            raise self._conflict_type("The input-turn record does not exist.") from error
        if version != expected_version:
            raise self._conflict_type("The input-turn record changed during the write.")
        return self._write(scope, payload)

    def _write(self, scope, payload):
        self._version += 1
        stored_turn = self._stored_turn_type(str(self._version), deepcopy(payload))
        self._records[scope] = (stored_turn.version, deepcopy(stored_turn.payload))
        return stored_turn

    def close(self):
        return None


class LocalFunctionRequest:
    def __init__(self, body, *, route_params=None, headers=None):
        self._body = deepcopy(body)
        self.route_params = route_params or {}
        self.params = {}
        self.headers = headers or {}

    def get_json(self):
        return deepcopy(self._body)


class LocalFunctionResponse:
    def __init__(self, function_response):
        self.status_code = function_response.status_code
        self.headers = function_response.headers
        self._body = function_response.get_body()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"Local Function returned {self.status_code}.", response=self)

    def json(self):
        return json_module.loads(self._body.decode("utf-8"))


class FakePipelineDownstreams:
    def __init__(self):
        self.dm_requests = []
        self.nlu_requests = []

    def make_request_to_nlu(self, _endpoint, natural_language_input, _session, _logger):
        self.nlu_requests.append(deepcopy(natural_language_input))
        utterance = natural_language_input["hypotheses"][0]["utterance"]
        return {
            "entities": [],
            "interpretations": [{
                "modality": "speech",
                "utterance": utterance,
                "moves": [{
                    "semantic_expression": "answer(destination(paris))",
                    "perception_confidence": 0.97,
                    "understanding_confidence": 1.0,
                }],
            }],
        }

    def make_request_to_dm(self, _endpoint, request, _logger):
        self.dm_requests.append(deepcopy(request))
        session = deepcopy(request["session"])
        if "natural_language_input" not in request["request"]:
            moves = []
        else:
            interpretations = request["request"].get("semantic_input", {}).get("interpretations", [])
            moves = [
                move["semantic_expression"] for interpretation in interpretations for move in interpretation["moves"]
            ]
        return {
            "context": {
                "active_ddd": "travel",
                "available_ddds": ["travel"],
            },
            "output": {
                "moves": moves,
                "expected_passivity": 3.0,
            },
            "session": session,
        }

    @staticmethod
    def unexpected_nlu_downstream_call(*_args, **_kwargs):
        raise AssertionError("The synthetic dialogue unexpectedly called an unstubbed downstream service.")

    @staticmethod
    def generate_nlg(_moves, _context, _session, _logger):
        return {
            "status": "success",
            "utterance": "Destination selected.",
        }


class LocalFunctionDispatcher:
    def __init__(self, handler_function_app, pipeline_function_app):
        self._handler_function_app = handler_function_app
        self._pipeline_function_app = pipeline_function_app
        self.frontend_requests = []
        self.internal_function_keys = []

    def post(self, url, *, data=None, json=None, headers=None, timeout=None, allow_redirects=True):
        request_body = deepcopy(json) if json is not None else json_module.loads(data)
        request_headers = headers or {}
        path = urlparse(url).path
        if "/api/interact/" in path:
            offer_id = unquote(path.rsplit("/", 1)[-1])
            self.frontend_requests.append({"body": request_body, "headers": request_headers})
            function_response = self._handler_function_app.handler_fn(
                LocalFunctionRequest(request_body, route_params={"offer_id": offer_id}, headers=request_headers)
            )
            return LocalFunctionResponse(function_response)

        if "/api/input-turn/" in path:
            self.internal_function_keys.append(request_headers.get("x-functions-key"))
            function_request = LocalFunctionRequest(request_body, headers=request_headers)
            if path.endswith("/input-turn/execute"):
                function_response = self._pipeline_function_app.input_turn_execute(function_request)
            elif path.endswith("/input-turn/commit-handler-context"):
                function_response = self._pipeline_function_app.input_turn_commit_handler_context(function_request)
            elif path.endswith("/input-turn/utterance-event"):
                function_response = self._pipeline_function_app.input_turn_utterance_event(function_request)
            else:
                raise AssertionError(f"Unexpected Pipeline Function endpoint: {path}")
            return LocalFunctionResponse(function_response)

        raise AssertionError(f"Unexpected local HTTP request: {url}")
