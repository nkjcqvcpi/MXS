# MXS 0.2.1 release readiness

## Verified locally

- The source version and build metadata are 0.2.1.
- Formatting, Ruff lint, and strict Pyright checks pass.
- The offline suite passes 95 tests, deselects seven hardware-dependent tests, and reports 93.16% aggregate coverage.
- The namespace release gate returns no matches outside the read-only submodules.
- Source and wheel builds pass; wheel inspection shows only the `mxs` package and distribution metadata.
- The wheel is restricted to `src/mxs`.
- Protocol constants and behavior are derived from the checked-in read-only Legacy-SW and Legacy-Documentation submodules.

## External validation status

Hardware gates remain pending because `/dev/tty.usbmodem2101` was absent on 2026-07-14. This includes the corrected version-list request, both baud transitions, the safe getter matrix, 512-frame async capture, RX/TX recording, reopen cycles, and the 1,800-second soak. MXS 0.2.1 must not be tagged or published until those commands pass on the target device.
