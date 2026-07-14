# Architecture

One `SerialWorker` owns pySerial. It drains a bounded TX queue, calls
`readinto()`, performs incremental framing once, classifies complete payloads,
and enqueues them. It does not decode application messages, call user code,
write files, or run NumPy/SciPy kernels.

`DecoderWorker` drains a high-priority control queue before an ordered stream
queue. `CommandManager` permits one uncorrelated ACK command at a time and
validates exact reply expectations. An ACK timeout closes the transport and
marks the session desynchronized.

`MessageHub` publishes typed messages to bounded sync and async subscriptions.
Async frame delivery uses `loop.call_soon_threadsafe`, not polling. Raw-wire,
parsed-message, and CIR recording use dedicated writers. Optional processing
uses a bounded thread, process, or inline pipeline and never receives work from
the serial thread.

All arrays are parsed with explicit little-endian NumPy dtypes and
`frombuffer()`. Pulse-Doppler and noisemap fragments preserve their counters,
range and frequency axes, instance, rates, quantization steps, and values.
