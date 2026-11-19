import asyncio
import time

from tala.utils.gpt_budget import RequestFailure


async def consume_model_stream(open_stream, on_chunk, *, first_content_seconds, completion_seconds, remaining,
                               timings=None, on_usage=None):
    """Consume one attempt; empty protocol messages do not satisfy its first-text deadline."""
    started = time.monotonic()
    first_deadline = started + min(first_content_seconds, remaining())
    completion_deadline = started + min(completion_seconds, remaining())
    stream = None
    first_content_at = None
    last_chunk = None
    last_usage_chunk = None
    finish_reasons = set()
    pending_chunks = []
    metrics = {} if timings is None else timings
    try:
        async with asyncio.timeout_at(min(first_deadline, completion_deadline)):
            stream = await open_stream()
        while True:
            deadline = min(completion_deadline, time.monotonic() + remaining())
            if first_content_at is None:
                deadline = min(deadline, first_deadline)
            try:
                async with asyncio.timeout_at(deadline):
                    chunk = await anext(stream)
            except StopAsyncIteration:
                break
            last_chunk = chunk
            if on_usage is not None and chunk.usage is not None:
                last_usage_chunk = chunk
            finish_reasons.update(choice.finish_reason for choice in chunk.choices if choice.finish_reason is not None)
            content = [choice.delta.content for choice in chunk.choices]
            if first_content_at is None:
                pending_chunks.append(chunk)
                if not any(text and text.strip() for text in content):
                    continue
                first_content_at = time.monotonic()
                for pending in pending_chunks:
                    on_chunk(pending)
                pending_chunks.clear()
                continue
            on_chunk(chunk)
        _validate_stream_completion(
            finish_reasons, first_content_at is not None, _stream_timings(started, first_content_at)
        )
        return last_chunk
    except TimeoutError as error:
        raise RequestFailure(
            "model", "first_content_timeout" if first_content_at is None else "completion_timeout",
            retryable=first_content_at is None,
            timings=_stream_timings(started, first_content_at),
        ) from error
    finally:
        metrics.update(_stream_timings(started, first_content_at))
        try:
            if on_usage is not None and last_usage_chunk is not None:
                on_usage(last_usage_chunk)
        finally:
            if stream is not None:
                await stream.close()


def _stream_timings(started, first_content_at):
    return {"model_seconds": time.monotonic() - started,
            "first_content_seconds": None if first_content_at is None else first_content_at - started}


def _validate_stream_completion(finish_reasons, has_content, timings):
    if "content_filter" in finish_reasons:
        raise RequestFailure("model", "refused", timings=timings)
    if "length" in finish_reasons:
        raise RequestFailure("model", "truncated", timings=timings)
    if not has_content:
        raise RequestFailure("model", "empty_completion", retryable=True, timings=timings)
    if "stop" not in finish_reasons:
        raise RequestFailure("model", "incomplete_completion", timings=timings)
