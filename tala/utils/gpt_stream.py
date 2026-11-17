import asyncio
import time

from tala.utils.gpt_budget import RequestFailure


async def consume_model_stream(open_stream, on_chunk, *, first_content_seconds, completion_seconds, remaining,
                               timings=None):
    """Consume one attempt; empty protocol messages do not satisfy its first-text deadline."""
    started = time.monotonic()
    first_deadline = started + min(first_content_seconds, remaining())
    completion_deadline = started + min(completion_seconds, remaining())
    stream = None
    first_content_at = None
    last_chunk = None
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
        if first_content_at is None:
            reasons = [choice.finish_reason for choice in last_chunk.choices] if last_chunk is not None else []
            if "content_filter" in reasons or "length" in reasons:
                raise RequestFailure("model", "refused" if "content_filter" in reasons else "truncated")
            raise RequestFailure("model", "empty_completion", retryable=True)
        return last_chunk
    except TimeoutError as error:
        raise RequestFailure(
            "model", "first_content_timeout" if first_content_at is None else "completion_timeout",
            retryable=first_content_at is None,
            timings={"model_seconds": time.monotonic() - started,
                     "first_content_seconds": None if first_content_at is None else first_content_at - started},
        ) from error
    finally:
        metrics.update({"model_seconds": time.monotonic() - started,
                        "first_content_seconds": None if first_content_at is None else first_content_at - started})
        if stream is not None:
            await stream.close()
