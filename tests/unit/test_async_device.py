import asyncio

import pytest

from mxs import AsyncX4M200, X4Config
from tests.conftest import FakeSerialFactory


@pytest.mark.asyncio
async def test_async_lifecycle_and_event_loop_responsiveness() -> None:
    radar = AsyncX4M200(port="fake", serial_factory=FakeSerialFactory())
    await radar.open()
    await radar.configure(X4Config())
    ticked = asyncio.Event()
    asyncio.get_running_loop().call_soon(ticked.set)
    await radar.start()
    await asyncio.wait_for(ticked.wait(), 0.2)
    frame = await radar.read_frame(timeout=1.0)
    assert frame.frame_counter == 42
    await radar.close()


@pytest.mark.asyncio
async def test_cancelled_reader_does_not_close_session() -> None:
    factory = FakeSerialFactory(data_before_ack=False)
    radar = AsyncX4M200(port="fake", serial_factory=factory)
    await radar.open()
    await radar.configure(X4Config())
    await radar.start()
    await radar.read_frame(timeout=1.0)
    task = asyncio.create_task(radar.read_frame())
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await radar.statistics()).frames_received == 1
    await radar.close()


@pytest.mark.asyncio
async def test_async_timeout_stop_and_frame_iterator() -> None:
    radar = AsyncX4M200(port="fake", serial_factory=FakeSerialFactory(data_before_ack=False))
    await radar.open()
    await radar.configure(X4Config())
    await radar.start()
    frame = await anext(radar.frames())
    assert frame.frame_counter == 42
    with pytest.raises(TimeoutError):
        await radar.read_frame(timeout=0.001)
    await radar.stop()
    assert (await radar.statistics()).frames_received == 1
    await radar.close()
