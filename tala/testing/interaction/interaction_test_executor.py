from tala.testing.interaction.interaction_tester import InteractionTester


class InteractionTestExecutorBase:
    def run_ng_interaction_test(self, testcase, port=None, use_streaming=False, offer=None, on_event=None):
        self._use_streaming = use_streaming
        self._on_event = on_event
        self._given_testcase(testcase)
        self._given_offer(offer)
        self._when_running_testcase(port)

    def _given_testcase(self, testcase):
        self._testcase = testcase

    def _given_offer(self, offer):
        self._offer = offer

    def _when_running_testcase(self, port):
        tester = InteractionTester(port, use_streaming=self._use_streaming, on_event=self._on_event)
        self._result = tester.run_testcase(self._testcase, self._offer)


class InteractionTestExecutorNoAssert(InteractionTestExecutorBase):
    @property
    def result(self):
        return self._result


class InteractionTestExecutorAssert(InteractionTestExecutorBase):
    def _when_running_testcase(self, port):
        super()._when_running_testcase(port)
        self._then_test_is_succesful()

    def _then_test_is_succesful(self):
        print(self._result["transcript"])
        assert self._result["success"], self._result["failure_description"]
