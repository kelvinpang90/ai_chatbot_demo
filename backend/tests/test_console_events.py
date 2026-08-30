import asyncio
import json

import pytest
from app.console import events
from app.routers import console


@pytest.fixture(autouse=True)
def clean_buffer():
    events.clear()
    yield
    events.clear()


def _emit_call(tool: str = "erp_search_sku", tool_use_id: str = "tu_1") -> None:
    events.emit(
        type=events.TOOL_START, tool=tool, tool_use_id=tool_use_id, input={"keyword": "earbuds"}
    )
    events.emit(
        type=events.TOOL_END,
        tool=tool,
        tool_use_id=tool_use_id,
        output="12 units",
        duration_ms=42,
        status="ok",
    )


def test_events_are_numbered_in_order():
    first = events.emit(type=events.TOOL_START, tool="a", tool_use_id="1")
    second = events.emit(type=events.TOOL_END, tool="a", tool_use_id="1", status="ok")

    assert second.seq > first.seq
    assert [e.seq for e in events.since(0)] == [first.seq, second.seq]


def test_since_returns_only_newer_events():
    first = events.emit(type=events.TOOL_START, tool="a", tool_use_id="1")
    second = events.emit(type=events.TOOL_END, tool="a", tool_use_id="1", status="ok")

    assert [e.seq for e in events.since(first.seq)] == [second.seq]
    assert events.since(second.seq) == []


def test_buffer_drops_the_oldest_instead_of_growing():
    for i in range(events.MAX_EVENTS + 10):
        events.emit(type=events.TOOL_START, tool="a", tool_use_id=str(i))

    kept = events.since(0)
    assert len(kept) == events.MAX_EVENTS
    assert kept[0].tool_use_id == "10"  # the first ten fell off the back


def test_the_endpoint_answers_as_an_event_stream():
    response = asyncio.run(console.stream(replay=True))

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"  # or nginx sits on the chunks


def test_replay_sends_the_buffered_calls_in_sse_frames():
    _emit_call()

    frames = asyncio.run(_take(console._event_stream(replay=True), count=2))

    assert frames[0].startswith("event: tool_start\n")
    assert frames[1].startswith("event: tool_end\n")
    payloads = [json.loads(frame.splitlines()[1].removeprefix("data: ")) for frame in frames]
    assert payloads[0]["input"] == {"keyword": "earbuds"}
    assert payloads[1]["duration_ms"] == 42
    assert payloads[1]["status"] == "ok"


async def _take(stream, count: int) -> list[str]:
    frames = []
    try:
        for _ in range(count):
            frames.append(await asyncio.wait_for(stream.__anext__(), timeout=5))
    finally:
        await stream.aclose()
    return frames


def test_a_fresh_subscriber_gets_what_happens_next_not_the_backlog():
    _emit_call(tool="stale_tool", tool_use_id="old")

    chunk = asyncio.run(_first_chunk_after_a_new_event())

    assert "stale_tool" not in chunk
    assert "fresh_tool" in chunk


async def _first_chunk_after_a_new_event() -> str:
    stream = console._event_stream(replay=False)
    pending = asyncio.create_task(stream.__anext__())
    try:
        # Let the generator take its cursor before anything new is emitted --
        # that ordering is exactly what a real subscriber experiences.
        await asyncio.sleep(0.05)
        events.emit(type=events.TOOL_START, tool="fresh_tool", tool_use_id="new")
        return await asyncio.wait_for(pending, timeout=5)
    finally:
        await stream.aclose()
