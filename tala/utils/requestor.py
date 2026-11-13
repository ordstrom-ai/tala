import uuid
import json
from threading import Event, Thread

import requests
from tala.utils.func import getenv, setup_logger
from tala.utils.log_context import correlation_headers, request_id_from_payload as correlation_request_id

REQUESTOR_URL = getenv("FUNCTION_ENDPOINT_REQUESTOR", "Define the Requestor function endpoint in the environment.")
REQUESTOR_BASE_URL = getenv(
    "FUNCTION_ENDPOINT_REQUESTOR_BASE", "Define the Requestor function endpoint base in the environment."
) or ""
CONNECTION_TIMEOUT = 3.05  # see requests documentation

DEFAULT_GPT_MODEL = getenv("DEFAULT_GPT_MODEL", "gpt-4o-2024-11-20")

TOP_PRIORITY = 1
HIGH_PRIORITY = 2
MEDIUM_PRIORITY = 10
LOW_PRIORITY = 200

MAX_NUM_CONNECTION_ATTEMPTS = 3

QUOTES = "'\""

READ_TIMEOUT = int(getenv("REQUESTOR_READ_TIMEOUT", "4") or 4)
READ_TIMEOUT_BASE = float(getenv("REQUESTOR_READ_TIMEOUT_BASE", READ_TIMEOUT) or READ_TIMEOUT)
READ_TIMEOUT_PER_TOKEN = float(getenv("REQUESTOR_READ_TIMEOUT_PER_TOKEN", "0.02") or 0.02)
READ_TIMEOUT_MAX = float(getenv("REQUESTOR_READ_TIMEOUT_MAX", "60") or 60)

requests_session = requests.Session()


class InvalidResponseError(Exception):
    pass


class ConnectionException(Exception):
    pass


class UnexpectedErrorException(Exception):
    pass


class GPTContentFilterError(Exception):
    def __init__(
        self,
        request_id,
        message,
        code=None,
        status=None,
        param=None,
        content_filter_result=None,
        error_payload=None,
    ):
        super().__init__(message)
        self.request_id = request_id
        self.code = code
        self.status = status
        self.param = param
        self.content_filter_result = content_filter_result
        self.error_payload = error_payload


class GPTStructuredOutputError(Exception):
    def __init__(self, request_id):
        super().__init__("Structured GPT response was not valid JSON.")
        self.request_id = request_id


def _is_content_filter_error(error_payload):
    try:
        if error_payload.get("code") == "content_filter":
            return True
        inner = error_payload.get("innererror", {})
        filter_result = inner.get("content_filter_result", {})
        jailbreak = filter_result.get("jailbreak", {})
        return bool(jailbreak.get("detected"))
    except Exception:
        return False


def unquote(possibly_quoted_string):
    def quoted(s):
        try:
            return s[0] in QUOTES and s[-1] in QUOTES
        except IndexError:
            return False

    if quoted(possibly_quoted_string):
        return possibly_quoted_string[1:len(possibly_quoted_string) - 1]
    return possibly_quoted_string


def make_request(endpoint, json_request, read_timeout, logger):
    def request_id_from_payload(payload):
        try:
            request_id = payload.get("request_id")
        except Exception:
            return None
        try:
            gpt_request = payload.get("gpt_request")
            return request_id or gpt_request.get("request_id")
        except Exception:
            return request_id

    def request(headers):
        logger.info(f"making request to: {endpoint}", body=json_request)
        try:
            attempt_no = 1
            success = False
            response_object = None
            while not success and attempt_no < MAX_NUM_CONNECTION_ATTEMPTS:
                try:
                    response_object = requests_session.post(
                        endpoint,
                        json=json_request,
                        headers=headers,
                        timeout=(CONNECTION_TIMEOUT, read_timeout * attempt_no)
                    )
                    response_object.raise_for_status()
                    success = True
                except Exception:
                    response_text = None
                    try:
                        if response_object is not None:
                            response_text = response_object.text
                    except Exception:
                        response_text = None
                    logger.exception(
                        f"Exception during request to {endpoint}. Attempt {attempt_no}/{MAX_NUM_CONNECTION_ATTEMPTS}.",
                        request_id=request_id_from_payload(json_request),
                        response_text=response_text,
                    )
                    logger.info(
                        f"Exception during request to {endpoint}. Attempt {attempt_no}/{MAX_NUM_CONNECTION_ATTEMPTS}",
                        request_id=request_id_from_payload(json_request),
                    )
                attempt_no += 1
            return response_object
        except Exception:
            logger.exception("Encountered exception during request")
            raise ConnectionException(f"Could not connect to {endpoint}")

    def decode(response_object):
        try:
            response = response_object.json()
            logger.debug(
                "received response",
                body=response,
                endpoint=endpoint,
                request_id=request_id_from_payload(json_request),
            )
            return response
        except (ValueError, AttributeError):
            response_text = None
            try:
                if response_object is not None:
                    response_text = response_object.text
            except Exception:
                response_text = None
            logger.exception("Encountered exception when decoding response", response_text=response_text)
            raise InvalidResponseError(f"Expected a valid JSON response from service but got {response_object}.")

    def validate(response):
        if "error" in response:
            error_payload = response.get("error") or {}
            if _is_content_filter_error(error_payload):
                return response
            description = error_payload.get("description") or error_payload.get("message") or "Unknown error"
            logger.error("Received error from service", description=description)
            raise UnexpectedErrorException(description)
        return response

    headers = {'Content-type': 'application/json'}
    headers.update(correlation_headers(logger, request_id=correlation_request_id(json_request)))
    response_object = request(headers)
    try:
        response = decode(response_object)
        return validate(response)
    except Exception:
        logger.exception(
            "An exception occurred when making the request",
            request_id=request_id_from_payload(json_request),
        )
        return {}


class GPTRequest:
    supports_response_format = True

    def __init__(
        self,
        allow_caching=False,
        logger=None,
        messages=None,
        temperature=0.1,
        max_tokens=50,
        max_retries=0,
        stop=None,
        default_gpt_response="[]",
        use_json=False,
        model=DEFAULT_GPT_MODEL,
        priority=MEDIUM_PRIORITY,
        request_id=None,
        reasoning_effort=None,
        read_timeout=None,
        allow_json_repair=True,
        response_format=None
    ):
        self.logger = logger if logger else setup_logger(__name__)
        self._request_id = request_id if request_id else str(uuid.uuid4())
        self.response_format = response_format
        self._requestor_arguments = {
            "gpt_request": {
                "messages": messages if messages else [],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "max_retries": max_retries,
                "stop": stop if stop else [],
                "default_gpt_response": default_gpt_response,
                "use_json": use_json,
                "model": model,
                "allow_caching": allow_caching,
                "reasoning_effort": reasoning_effort
            },
            "priority": priority,
            "request_id": self._request_id,
        }
        if response_format is not None:
            self._requestor_arguments["gpt_request"]["response_format"] = response_format
        self._read_timeout_base = READ_TIMEOUT_BASE
        self._read_timeout_per_token = READ_TIMEOUT_PER_TOKEN
        self._read_timeout_max = READ_TIMEOUT_MAX
        self._use_dynamic_timeout = read_timeout is None
        if self._use_dynamic_timeout:
            self._read_timeout = self._calculate_read_timeout(max_tokens)
        else:
            self._read_timeout = read_timeout
        self._response = None
        self._done = Event()
        self._allow_json_repair = bool(allow_json_repair and use_json)
        self._json_repair_attempted = False

    @property
    def response(self):
        try:
            self._done.wait()
            response_body = None
            response_payload = None
            try:
                response_payload = self._response
            except Exception:
                response_payload = None
            if response_payload:
                if "error" in response_payload and _is_content_filter_error(response_payload.get("error") or {}):
                    error_payload = response_payload.get("error") or {}
                    inner = error_payload.get("innererror", {})
                    content_filter_result = inner.get("content_filter_result")
                    raise GPTContentFilterError(
                        request_id=self._request_id,
                        message=error_payload.get("message") or "The response was filtered due to content policy.",
                        code=error_payload.get("code"),
                        status=error_payload.get("status"),
                        param=error_payload.get("param"),
                        content_filter_result=content_filter_result,
                        error_payload=error_payload,
                    )
                try:
                    response_body = response_payload.get("response_body")
                except Exception:
                    response_body = None
            if response_body is not None:
                return response_body
        except GPTContentFilterError:
            raise
        except Exception:
            self.logger.exception()

        self.logger.info("Returning default response", default_response=self.default_gpt_response)
        return self.default_gpt_response

    @property
    def completion_status(self):
        self._done.wait()
        try:
            response_payload = self._response
            status = response_payload.get("completion_status")
            if status:
                return status
            if response_payload.get("status") == "filtered":
                return "refused"
            if response_payload.get("response_body") is not None:
                return "completed"
        except Exception:
            pass
        return "error"

    @property
    def json_response(self):
        try:
            return json.loads(self.response)
        except GPTContentFilterError:
            raise
        except json.JSONDecodeError as error:
            if self.response_format is not None:
                self.logger.error(
                    "Structured GPT response was not valid JSON",
                    request_id=self._request_id,
                )
                raise GPTStructuredOutputError(self._request_id) from error
            if self._allow_json_repair and not self._json_repair_attempted:
                self._json_repair_attempted = True
                current_max_tokens = self.max_tokens
                self.logger.warning(
                    "response json invalid, retrying repair",
                    request_id=self._request_id,
                    max_tokens=current_max_tokens,
                    retry_action="json_repair",
                )
                self.update_with_last_assistant_and_next_user_message("Return valid JSON only. No extra text.")
                self.logger.info(
                    "json repair retry prepared",
                    request_id=self._request_id,
                    max_tokens=self.max_tokens,
                )
                self.make()
                try:
                    return json.loads(self.response)
                except (GPTContentFilterError, json.JSONDecodeError):
                    pass
            self.logger.exception(
                "decoding response raised JSONDecodeError",
                response_content=self.response,
                gpt_max_tokens=self.max_tokens
            )
        except Exception as e:
            self.logger.info("json decoding response raised Exception", exception=e)

        self.logger.info("Returning default response", default_response=self.default_gpt_response)
        return json.loads(self.default_gpt_response)

    @property
    def text_response(self):
        return unquote(self.response)

    @property
    def default_gpt_response(self):
        return self._requestor_arguments["gpt_request"]["default_gpt_response"]

    @property
    def max_tokens(self):
        return self._requestor_arguments["gpt_request"]["max_tokens"]

    @property
    def messages(self):
        return self._requestor_arguments["gpt_request"]["messages"]

    @property
    def request_id(self):
        return self._request_id

    @property
    def system_message(self):
        return self._requestor_arguments["gpt_request"]["messages"][0]

    def make(self):
        def do_request():
            self.logger.info("make GPTRequest", request_id=self._request_id)
            try:
                self._response = make_request(REQUESTOR_URL, self._requestor_arguments, self._read_timeout, self.logger)
                self.logger.info("received response", request_id=self._request_id, response=self._response)
            except Exception:
                self._response = {}
                self.logger.exception("GPTRequest failed", request_id=self._request_id)
            self._done.set()

        self.logger.info("Start request thread", request_id=self._request_id)
        Thread(target=do_request, daemon=True).start()

    def add_system_message(self, message):
        self._add_message("system", message)

    def _add_message(self, role, message):
        self._requestor_arguments["gpt_request"]["messages"].append({"role": role, "content": message})

    def add_messages(self, messages):
        self._requestor_arguments["gpt_request"]["messages"].extend(messages)

    def add_user_message(self, message):
        self._add_message("user", message)

    def add_assistant_message(self, message):
        self._add_message("assistant", message)

    def update_with_last_assistant_and_next_user_message(self, user_message):
        self.add_assistant_message(self.text_response)
        self.add_user_message(user_message)
        self._double_max_tokens()
        self._done.clear()
        self._response = None

    def _double_max_tokens(self):
        self._requestor_arguments["gpt_request"]["max_tokens"] *= 2
        self._update_read_timeout()

    def _update_read_timeout(self):
        if self._use_dynamic_timeout:
            self._read_timeout = self._calculate_read_timeout(self.max_tokens)

    def _calculate_read_timeout(self, max_tokens):
        try:
            base_timeout = float(self._read_timeout_base)
            per_token = float(self._read_timeout_per_token)
            max_timeout = float(self._read_timeout_max) if self._read_timeout_max is not None else None
            timeout = base_timeout + (per_token * (max_tokens or 0))
        except Exception:
            return READ_TIMEOUT_BASE
        if max_timeout and max_timeout > 0:
            timeout = min(timeout, max_timeout)
        if timeout <= 0:
            return READ_TIMEOUT_BASE
        return timeout


class GPTRequestForDeploymentAssignment(GPTRequest):
    def make(self):
        def do_request():
            self.logger.info("make GPTRequestForDeploymentAssignment", request_id=self._request_id)
            try:
                self._response = make_request(
                    REQUESTOR_BASE_URL + "/assign-deployment", self._requestor_arguments, self._read_timeout,
                    self.logger
                )
                self.logger.info("received response", request_id=self._request_id, response=self._response)
            except Exception as e:
                self.logger.exception()
                raise e
            self._done.set()

        self.logger.info("Start request thread", request_id=self._request_id)
        Thread(target=do_request, daemon=True).start()


class UpdateTPMRequest:
    def __init__(
        self, request_id=None, deployment_name=None, deployment_resource=None, total_tokens_used=0, logger=None
    ):
        self._request_id = request_id if request_id else str(uuid.uuid4())
        self._requestor_arguments = {
            "request_id": self._request_id,
            "deployment_name": deployment_name,
            "deployment_resource": deployment_resource,
            "total_tokens_used": total_tokens_used
        }
        self.logger = logger if logger else setup_logger(__name__)
        self._response = None

    def make(self):
        def do_request():
            self.logger.info("make UpdateTPMRequest", arguments=self._requestor_arguments, request_id=self._request_id)

            self._response = make_request(
                REQUESTOR_BASE_URL + "/update-tpm", self._requestor_arguments, 2.0, self.logger
            )
            self.logger.info("received response", request_id=self._request_id, response=self._response)

        self.logger.info("Start request thread", request_id=self._request_id)
        Thread(target=do_request, daemon=True).start()
