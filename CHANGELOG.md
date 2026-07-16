# Changelog

## 0.2.5 - 2026-07-16

- Add an explicit `OPENING` state and prevent asynchronous serial, decoder, callback, recorder, or worker-termination failures from being overwritten by `OPEN`.
- Flush callback work submitted during baud probing and require every owned worker to remain healthy before accepting a candidate.
- Accept both source-defined and observed Annapurna 1.6.6 reply content IDs while retaining strict datatype, info, element-count, element-size, and payload-length validation.
- Enforce all three output-exclusivity pairs through one normal/debug transaction with preflight conflict rejection and postcondition verification.
- Restore baseline profile ID `0` through verified no-profile state or source-backed module reset, then verify outputs, STOP, 115200 baud, PING, and worker shutdown.
- Replace synthetic firmware, fake router, and fake discovery tests with mutations of packets captured from the connected X4M200.
- Require explicit method-level API-parity evidence and verify that each cited pytest node directly references its documented API symbol.
- Give every unsupported method an explicit documented signature and verify positional and keyword calls raise `UnsupportedFirmwareError` without transmission.

## 0.2.4 - 2026-07-15

- Serialize every structured interface command through the session operation lock, including complete filesystem and output-state transactions.
- Preserve baud-candidate cleanup failures after worker termination and abort automatic detection on callback, recorder, decoder, or shutdown errors.
- Reject mutually exclusive output enables from fresh device queries before transmission, then resynchronize the complete group after ACK.
- Restore the original profile and supported output states after stateful tests, force STOP at 115200 baud, and reject leaked MXS workers.
- Restore deterministic protocol, concurrency, recording, processing, CLI, parity, and real-callback regressions under the mandatory hardware preflight.
- Bind every API-parity row to an existing pytest node and an explicit executed, unsupported, unsafe, or non-executed evidence classification.

## 0.2.3 - 2026-07-15

- Reject extended respiration, periodic noisemap storage, undocumented XEP controls, and X4Driver I2C access with `UnsupportedFirmwareError` before transmission.
- Serialize unsafe authorization, sensor-mode verification, and action under the same session operation lock used by profile and acquisition state changes.
- Keep sessions in `ERROR` with their worker reference intact when any owned transport worker survives shutdown.
- Synchronize mutually exclusive output controls from device state and invalidate the cache across profile, reset, close, and reopen boundaries.
- Remove serial-factory injection, simulated firmware responses, checked-in traffic fixtures, offline pytest suites, and the long soak test.
- Require every pytest test to use the real X4M200 at `/dev/tty.usbmodem2101` and fail setup when it is unavailable or busy.
- Validate real identity, both baud rates, RF and IQ acquisition, 512-frame async acquisition, application messages, recording, reopen, unsupported behavior, and disabled unsafe operations.

## 0.2.2 - validation pending

- Isolated every baud probe in a fresh command manager, router, subscription set, and serial worker.
- Made synchronous and asynchronous shutdown preserve the first error while still closing routers, workers, bridges, files, and consumer queues.
- Removed recorder shutdown deadlocks and restored the legacy raw callback's RX-only contract while retaining direction-aware wire recording.
- Required a confirmed firmware STOP state before destructive operations, except documented MANUAL-safe frame injection and register writes.
- Serialized complete filesystem reads and mutations under one session lock.
- Prevented cancelled asyncio waiters from entering a blocking queue path on the event-loop thread.
- Corrected the complete Legacy-SW profile-ID set and retained `SLEEP` as its distinct `0x00F17B17` identifier.

## 0.2.1 - validation pending

- Removed the legacy package and command namespace; MXS is now the sole package, CLI, documentation name, test namespace, and environment-variable prefix.
- Eliminated the duplicate lossless subscription in async acquisition and made async topic waiter registration and cancellation lossless.
- Corrected GPIO setup and feature definitions, direct baud-rate transitions, and system-information IDs.
- Desynchronize after every uncorrelated command timeout and preserve that state through best-effort stop.
- Propagate recorder failures, timestamp RX and TX at the transport boundary, and preserve those timestamps on disk.
- Added state-aware unsafe-operation guards, including a dedicated noisemap flash-write gate.
- Corrected filesystem create/write/commit transactions and serialized mutations.
- Track frame counters by CIR stream and route downconverted data to `raw_iq`.
- Made capability results conservative and retained structured probe diagnostics.

## 0.2.0 - 2026-07-14

- Established `mxs` as the public import and command name.
- Added datatype-aware reply models, command-specific expectations, timeout desynchronization, recovery, and object reopening.
- Split serial I/O, prioritized decoding, recording, async delivery, and optional processing into bounded stages.
- Added typed application, generic DATA, SYSTEM, baseband, respiration, vital-sign, pulse-Doppler, and noisemap messages.
- Added structured module, profile, output, XEP/X4Driver, GPIO, noisemap, parameter-file, filesystem, and gated unsafe interfaces.
- Added capability reporting, richer discovery, SciPy processing, parsed-message recording, a direction-aware wire format, and limited XTAN-05 import.
- Corrected REPLY length semantics: the wire field is an element count, not a byte count.

## 0.1.0

- Initial raw RF and downconverted IQ acquisition library.
