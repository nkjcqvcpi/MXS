# Changelog

## 0.2.0 - 2026-07-14

- Renamed the import and CLI from `x4cir` to `mxs`; retained a compatibility export for the 0.1 top-level classes.
- Added datatype-aware reply models, command-specific expectations, timeout desynchronization, recovery, and object reopening.
- Split serial I/O, prioritized decoding, recording, async delivery, and optional processing into bounded stages.
- Added typed application, generic DATA, SYSTEM, baseband, respiration, vital-sign, pulse-Doppler, and noisemap messages.
- Added structured module, profile, output, XEP/X4Driver, GPIO, noisemap, parameter-file, filesystem, and gated unsafe interfaces.
- Added capability reporting, richer discovery, SciPy processing, parsed-message recording, a direction-aware wire format, and limited XTAN-05 import.
- Corrected REPLY length semantics: the wire field is an element count, not a byte count.

## 0.1.0

- Initial raw RF and downconverted IQ acquisition library.
