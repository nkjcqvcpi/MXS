# Changelog

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
