# Architecture

One `SerialWorker` thread owns the pySerial object. It drains a bounded TX
queue, performs chunked `readinto()` calls, feeds one ordered mixed MCP decoder,
and routes decoded messages. `CommandManager` permits one uncorrelated control
request at a time. CIR consumers use bounded queues with either lossless-error
or drop-oldest behavior. The asynchronous API delegates blocking session work
to `asyncio.to_thread`, so it shares the same parser, router, and state machine.

Raw wire recording occurs before parsing. Parsed recording uses NumPy bulk
operations and a separate chunk writer for long acquisitions. No sample is
parsed one float at a time.

