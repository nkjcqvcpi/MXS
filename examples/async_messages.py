import asyncio

from mxs import AsyncX4M200, X4Config


async def main() -> None:
    async with AsyncX4M200() as device:
        await device.configure(X4Config())
        await device.start()
        print(await device.read_frame(timeout=2))


asyncio.run(main())
