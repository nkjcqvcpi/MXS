# MXS 0.2.0 release readiness

The package builds and its current automated gates pass, but it does not yet satisfy every requirement in `plan.md`. A successful wheel build is therefore not evidence that the 0.2.0 definition of done has been met.

## Verified

- Formatting, lint, strict type checking, API-path parity, and offline tests pass.
- Total package coverage is 90.02%.
- The safe hardware suite passes with five tests and one manual-disconnect skip.
- A 30-minute raw-recording soak captured 30,665 frames and 104,479,134 bytes with no gaps, checksum errors, malformed packets, drops, sustained backlog, or leaked threads; memory grew by 0.8125 MiB.
- Framing throughput on both checked-in recordings exceeds ten times the 921,600-baud byte rate.
- Source and wheel distributions build as version 0.2.0.

## Release blockers

- The CLI lacks the planned `set`, `outputs`, `messages`, `noisemap`, `gpio`, and `unsafe` command groups.
- Per-component coverage remains below the plan thresholds: message decoding is 85%, transport is 83%, and related routing and session modules are 89% and 77%. The aggregate threshold passes.
- Hardware validation does not yet cover every safe getter, recoverable setter with restoration, application profile output, pulse-Doppler/noisemap stream, or safe filesystem read.
- The physical USB-disconnect test requires a person to remove the device and remains skipped. Reset re-enumeration also lacks a live acceptance test.
- The wire format can store TX direction, but the serial transport currently supplies only RX chunks to its recorder callback. Recorder timestamps are assigned on the writer thread rather than at serial receipt.
- The performance report measures framing and the end-to-end soak. It does not contain separate decoder, router, recorder, parsed-message, NumPy, or SciPy benchmarks for every plan scenario.
- The parity table resolves API paths and final statuses, but its command and test columns are category-level classifications rather than a method-by-method command-ID and evidence matrix.

These gaps should be closed before tagging 0.2.0 as complete.
