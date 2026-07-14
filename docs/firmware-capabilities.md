# Firmware capabilities

## Tested device

Safe hardware validation on 2026-07-14 used:

| Field | Value |
|---|---|
| Port | `/dev/tty.usbmodem2101` |
| Item number | `000167-007` |
| Order code | `X4M200` |
| Firmware ID | `Annapurna` |
| Version | `1.6.6` |
| Build | `1.6.6+0.sha.039b0b3c581a0087885a2a1ed627d00a6d1df05e` |
| Serial number | `100000128815` |

System information, sensor mode, profile ID, raw RF, downconverted IQ, reopen, and the documented X4Driver getters were observed. The configured X4Driver values were FPS 0, iterations 16, pulses per step 300, DAC 949 to 1100, TX power 2, downconversion off, 846 bins, frame area approximately -0.4373 to 5.0025 m, offset 0.18 m, center band 3, and PRF divider 16.

Application getters require a loaded profile on this firmware. With profile ID 0, sensitivity and TX-frequency getters return firmware error 1; several other application getters do not reply. Earlier validation used an incorrect version-list ID and is not evidence for the corrected `0x07` request. MXS records probe failures by category and does not infer support from product identity.

Periodic noisemap storage, XEP normalization/phase-noise/decimation/number-format/legacy-output controls, and X4Driver I2C access appear in public host headers but have no command producer in the checked-in target source. They raise `UnsupportedFirmwareError` rather than emitting guessed bytes.
