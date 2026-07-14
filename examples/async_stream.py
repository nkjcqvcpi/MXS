import asyncio

from mxs import AsyncX4M200, X4Config


async def main() -> None:
    async with AsyncX4M200() as radar:
        await radar.configure(X4Config(downconversion=True))
        await radar.start()
        async for frame in radar.frames():
            print(frame.frame_counter, frame.samples.shape, frame.sequence_gap)


asyncio.run(main())
