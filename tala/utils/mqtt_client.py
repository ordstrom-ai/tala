import threading
import json

import paho.mqtt.client as mqtt

from tala.utils import sse_client


class MQTTClientException(BaseException):
    pass


class MQTTClient(sse_client.AbstractSSEClient):
    transport = "mqtt"
    sessions = {}

    def __init__(self, client_id_base, logger, endpoint, port=None):
        super().__init__(client_id_base, logger, endpoint, port)

        def on_connect(client, userdata, connect_flags, reason_code, properties):
            self.logger.info('CONNACK received', reason_code=reason_code, properties=properties)
            self._connected.set()

        self._connected = threading.Event()

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            transport="websockets",
            reconnect_on_failure=True,
            clean_session=True,
            client_id=self._client_id
        )
        self._client.on_connect = on_connect
        self._client.tls_set()

    def start(self):
        self.logger.info("connecting to", endpoint=self._endpoint, port=self._port)
        self._client.connect(self._endpoint, self._port)
        self._client.loop_start()

    def _get_topic(self, streamer_session):
        return f'tm/id/{streamer_session["session_id"]}'

    def _stream_to_frontend(self, streamer_session, message):
        def remove_final_space(message):
            if "data" in message:
                message["data"] = message["data"].strip()
            return message

        streamer_session["message_counter"] += 1
        self.logger.debug(
            "MQTT Client streaming to frontend",
            message=message,
            session_id=streamer_session["session_id"],
            client_id=self.client_id
        )
        self._connected.wait()
        payload = json.dumps(message)
        response_send_started = self._start_first_response_content_send(streamer_session, message, "mqtt")
        try:
            self._client.publish(self._get_topic(streamer_session), payload)
        except Exception as error:
            if response_send_started:
                self._log_first_response_content_send_failure(streamer_session, "mqtt", error)
            raise

    def close_session(self, session_id):
        streamer_session = self.sessions[session_id]
        streamer_exception = streamer_session.get("streaming_exception")
        if streamer_exception:
            raise MQTTClientException(
                f'{streamer_exception} was raised during streaming in {streamer_session["session_id"]}. Streamed: {self._streamed}.'
            )
        self.logger.info("close session", client_id=self.client_id, session_id=streamer_session["session_id"])
        self.logger.info(
            "Streamed in session",
            num_messages=streamer_session["message_counter"],
            streamed=streamer_session["streamed"]
        )
        self._reset_logger()
        del self.sessions[session_id]


class ChunkJoiner(sse_client.ChunkJoiner):
    pass


class StreamIterator(sse_client.StreamIterator):
    pass
