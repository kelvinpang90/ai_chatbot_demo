import asyncio
import json
from unittest.mock import patch

import pytest
from app.config import settings
from app.console import cost, events
from app.main import app
from app.routers import console
from fastapi.testclient import TestClient

TOKEN = "console-token-for-tests"


@pytest.fixture(autouse=True)
def clean_buffer():
    events.clear()
    yield
    events.clear()


@pytest.fixture(autouse=True)
def console_token():
    """Every test here talks to a console that has a token configured.

    Without this the router refuses before it reaches anything worth testing,
    which is the point of the two tests below that opt out of it explicitly.
    """
    with patch.object(settings, "console_token", TOKEN):
        yield


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
    """Called directly, because the response body here never ends.

    The token check moved into a dependency when task 37.1 put the transcript
    endpoints behind the same gate, so this call skips it -- which is fine for
    what this test is about, and the two below drive the gate over HTTP where a
    refused request returns instead of opening an endless stream.
    """
    response = asyncio.run(console.stream(replay=True))

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"  # or nginx sits on the chunks


def test_the_stream_opens_by_naming_the_process_behind_it():
    """Two jobs for one frame.

    The headers have to leave at once or a buffering proxy sits on them -
    measured on the deployed site, without a first byte the page showed
    "connecting..." until the first keepalive, up to fifteen seconds into a demo.
    And the boot id is how a console tells a replayed event from a new one after
    a redeploy, since sequence numbers start over with the process.
    """
    frames = asyncio.run(_take(console._event_stream(replay=True), count=1))

    assert frames[0].startswith("event: hello\n")
    assert json.loads(frames[0].splitlines()[1].removeprefix("data: ")) == {
        "boot_id": events.BOOT_ID
    }


def test_replay_sends_the_buffered_calls_in_sse_frames():
    _emit_call()

    _hello, *frames = asyncio.run(_take(console._event_stream(replay=True), count=3))

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


@pytest.mark.parametrize("query", ["", "?token=", "?token=not-the-token"])
def test_the_stream_refuses_without_the_right_token(query):
    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            assert http.get(f"/console/stream{query}").status_code == 401


def test_an_unconfigured_token_closes_the_stream_rather_than_opening_it():
    """The feed carries live orders and customer records, and nginx forwards it.

    A missing secret must not read as "no gate needed" -- that is exactly how
    this endpoint spent task 3 to task 12 unprotected.
    """
    with patch.object(settings, "console_token", ""):
        with TestClient(app) as http:
            assert http.get("/console/stream?token=anything").status_code == 503


def test_a_usage_event_carries_the_ringgit_it_cost():
    tokens = {"input": 1000, "output": 500, "cache_write": 0, "cache_read": 0}
    events.emit(
        type=events.USAGE,
        model="claude-opus-5",
        tokens=tokens,
        cost_myr=cost.cost_myr("claude-opus-5", tokens),
    )

    (event,) = events.since(0)
    assert event.tool == ""  # a usage event belongs to the turn, not to a tool
    # 1000 in at $5/MTok + 500 out at $25/MTok = $0.0175.
    assert event.cost_myr == pytest.approx(0.0175 * cost.USD_TO_MYR)


def test_cached_tokens_are_billed_at_their_own_rates():
    plain = cost.cost_myr("claude-sonnet-5", _tokens(input=1000))
    written = cost.cost_myr("claude-sonnet-5", _tokens(cache_write=1000))
    read = cost.cost_myr("claude-sonnet-5", _tokens(cache_read=1000))

    assert written == pytest.approx(plain * cost.CACHE_WRITE_MULTIPLIER)
    assert read == pytest.approx(plain * cost.CACHE_READ_MULTIPLIER)


def test_an_unpriced_model_is_quoted_at_the_dearest_rate_we_know():
    """Quoting low would be a promise we cannot keep once the bill arrives."""
    unknown = cost.cost_myr("claude-something-new", _tokens(input=1000, output=1000))
    dearest = cost.cost_myr("claude-opus-5", _tokens(input=1000, output=1000))

    assert unknown == dearest


def _tokens(**counts: int) -> dict[str, int]:
    return {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0, **counts}


async def _first_chunk_after_a_new_event() -> str:
    stream = console._event_stream(replay=False)
    await stream.__anext__()  # the hello frame that flushes the headers
    pending = asyncio.create_task(stream.__anext__())
    try:
        # Let the generator take its cursor before anything new is emitted --
        # that ordering is exactly what a real subscriber experiences.
        await asyncio.sleep(0.05)
        events.emit(type=events.TOOL_START, tool="fresh_tool", tool_use_id="new")
        return await asyncio.wait_for(pending, timeout=5)
    finally:
        await stream.aclose()
