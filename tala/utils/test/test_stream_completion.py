import asyncio
from types import SimpleNamespace

import pytest

from tala.utils.gpt_budget import RequestFailure
from tala.utils.gpt_stream import consume_model_stream


class TestStreamCompletion:
    @pytest.mark.parametrize(
        "finish_reason,expected_reason", [
            ("length", "truncated"),
            ("content_filter", "refused"),
            (None, "incomplete_completion"),
        ]
    )
    @pytest.mark.parametrize("text", [None, "answer"])
    def test_non_successful_completions_are_classified_even_after_text_and_usage(
        self, finish_reason, expected_reason, text
    ):
        self.given_a_stream_ending_with_usage_after_its_finish_reason(finish_reason, text)
        self.when_the_model_stream_is_consumed()
        self.then_the_non_success_is_reported_without_restarting_output(expected_reason, text)

    def given_a_stream_ending_with_usage_after_its_finish_reason(self, reason, text):
        self.closed = False
        self.forwarded = []
        self.failure = None
        self.result = None
        self.chunks = iter([
            self.chunk(text, None),
            self.chunk(None, reason),
            SimpleNamespace(choices=[], usage=SimpleNamespace()),
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

    @staticmethod
    def chunk(text, reason):
        return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=reason)])

    def when_the_model_stream_is_consumed(self):
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
                )
            )
        except RequestFailure as error:
            self.failure = error

    def then_the_non_success_is_reported_without_restarting_output(self, reason, text):
        if text is None and reason == "incomplete_completion":
            reason = "empty_completion"
        assert self.failure is not None, "An incomplete model stream was accepted as successful."
        assert self.failure.phase == "model"
        assert self.failure.reason == reason
        assert self.failure.retryable == (reason == "empty_completion")
        assert self.failure.timings["model_seconds"] >= 0
        assert (self.failure.timings["first_content_seconds"] is None) == (text is None)
        assert self.result is None
        assert self.closed
        assert bool(self.forwarded) == (text is not None)

    def test_a_successful_finish_is_retained_when_usage_arrives_last(self):
        self.given_a_stream_ending_with_usage_after_its_finish_reason("stop", "answer")
        self.when_the_model_stream_is_consumed()
        self.then_the_answer_and_usage_are_returned_without_failure()

    def then_the_answer_and_usage_are_returned_without_failure(self):
        assert self.failure is None
        assert self.result.choices == []
        assert len(self.forwarded) == 3
        assert self.forwarded[0].choices[0].delta.content == "answer"
        assert self.closed
