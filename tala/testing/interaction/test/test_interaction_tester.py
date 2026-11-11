from unittest.mock import Mock

import pytest

from tala.model.user_move import DDDSpecificUserMove
from tala.testing.interaction.interaction_tester import InteractionTester


class TestInteractionTesterMovePrefix:
    def test_prefixed_move_overrides_target_ddd(self):
        tester = InteractionTester(port=None)
        tester._ddd_name = "fallback"

        move = tester._create_user_move("other:answer(hour_to_set(11))")

        assert isinstance(move, DDDSpecificUserMove)
        assert move.ddd == "other"
        assert move.semantic_expression == "answer(hour_to_set(11))"

    def test_unprefixed_move_uses_target_ddd(self):
        tester = InteractionTester(port=None)
        tester._ddd_name = "hello_world"

        move = tester._create_user_move("answer(hour_to_set(11))")

        assert isinstance(move, DDDSpecificUserMove)
        assert move.ddd == "hello_world"

    def test_prefixed_move_without_target_ddd(self):
        tester = InteractionTester(port=None)

        move = tester._create_user_move("hello_world:answer(hour_to_set(11))")

        assert isinstance(move, DDDSpecificUserMove)
        assert move.ddd == "hello_world"

    def test_icm_move_does_not_parse_as_prefix(self):
        tester = InteractionTester(port=None)
        tester._ddd_name = "hello_world"

        move = tester._create_user_move("icm:acc*pos")

        assert isinstance(move, DDDSpecificUserMove)
        assert move.ddd == "hello_world"
        assert move.semantic_expression == "icm:acc*pos"


class TestInteractionTesterServiceResultSession:
    @pytest.mark.parametrize("result_type", ("query_results", "action_results", "validation_results"))
    def test_follow_up_turn_uses_session_returned_by_service_result(self, result_type):
        self.given_interaction_tester(result_type)
        self.when_service_result_continuation_completes()
        self.when_next_passivity_turn_is_requested()
        self.then_passivity_request_uses_updated_session()

    def given_interaction_tester(self, result_type):
        self._tester = InteractionTester(port=None)
        self._client = Mock()
        self._tester._client = self._client
        self._tester._request_times = []
        self._result_type = result_type
        self._service_session = {"session_id": "service-invocation"}
        self._updated_session = {"session_id": "after-service-result"}
        self._tester._session_data = self._service_session
        self._tester._latest_response = {
            "original_request": {"semantic_input": {"interpretations": [], "entities": []}},
            "session": self._service_session,
        }
        self._client.make_request.return_value = {"session": self._updated_session}
        self._client.request_passivity.return_value = {"session": {"session_id": "after-passivity"}}

    def when_service_result_continuation_completes(self):
        self._tester._make_results_request_for_dme(self._result_type, {})

    def when_next_passivity_turn_is_requested(self):
        self._tester._request_passivity()

    def then_passivity_request_uses_updated_session(self):
        self._client.request_passivity.assert_called_once_with(self._updated_session)
