import asyncio
from types import SimpleNamespace

import pytest

from tala.utils.gpt_budget import RequestFailure
from tala.utils.gpt_stream import consume_model_stream


class TestStreamUsage:
    @pytest.mark.parametrize(
        "text,finish,reason", [
            ("answer", "stop", None),
            ("answer", "length", "truncated"),
            ("answer", "content_filter", "refused"),
            ("answer", None, "incomplete_completion"),
            (None, "content_filter", "refused"),
            (None, "stop", "empty_completion"),
        ]
    )
    def test_usage_is_observed_once_independently_of_completion_and_text(self, text, finish, reason):
        self.given_a_model_stream_with_terminal_usage(text, finish)
        self.when_the_stream_and_its_usage_are_consumed()
        self.then_the_last_usage_is_preserved_without_becoming_generated_text(reason, text)

    def given_a_model_stream_with_terminal_usage(self, text, finish):
        self.observed = []
        self.forwarded = []
        self.closed = False
        self.failure = None
        self.result = None
        self.usage = SimpleNamespace(prompt_tokens=10, completion_tokens=7, total_tokens=17)
        self.chunks = iter([
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=None)], usage=None
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason=finish)], usage=None
            ),
            SimpleNamespace(choices=[], usage=SimpleNamespace(total_tokens=15)),
            SimpleNamespace(choices=[], usage=self.usage),
        ])
        scenario = self

        class Stream:
            async def __anext__(self):
                try:
                    return next(scenario.chunks)
                except StopIteration:
                    raise StopAsyncIteration

            async def close(self):
                scenario.closed = True

        self.stream = Stream()

    def when_the_stream_and_its_usage_are_consumed(self):
        async def open_stream():
            return self.stream

        try:
            self.result = asyncio.run(
                consume_model_stream(
                    open_stream,
                    self.forwarded.append,
                    first_content_seconds=1,
                    completion_seconds=1,
                    remaining=lambda: 1,
                    on_usage=self.observed.append,
                )
            )
        except RequestFailure as error:
            self.failure = error

    def then_the_last_usage_is_preserved_without_becoming_generated_text(self, reason, text):
        assert len(self.observed) == 1
        assert self.observed[0].usage is self.usage
        assert self.closed
        assert bool(self.forwarded) == (text is not None)
        if reason is None:
            assert self.failure is None
            assert self.result.usage is self.usage
        else:
            assert self.result is None
            assert self.failure.reason == reason

    def test_a_stream_without_usage_does_not_invent_an_accounting_observation(self):
        self.given_a_model_stream_with_terminal_usage("answer", "stop")
        self.given_the_provider_omits_usage()
        self.when_the_stream_and_its_usage_are_consumed()
        self.then_no_usage_observation_is_fabricated()

    def given_the_provider_omits_usage(self):
        self.chunks = iter([
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="answer"), finish_reason=None)], usage=None
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason="stop")], usage=None
            ),
        ])

    def then_no_usage_observation_is_fabricated(self):
        assert self.failure is None
        assert self.observed == []
        assert self.result.usage is None
        assert self.closed
