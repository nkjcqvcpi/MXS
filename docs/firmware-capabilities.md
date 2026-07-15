# Firmware capabilities

## Tested device

Safe hardware validation on 2026-07-15 used:

| Field | Value |
|---|---|
| Port | `/dev/tty.usbmodem2101` |
| Item number | `000167-007` |
| Order code | `X4M200` |
| Firmware ID | `Annapurna` |
| Version | `1.6.6` |
| Build | `1.6.6+0.sha.039b0b3c581a0087885a2a1ed627d00a6d1df05e` |
| Serial number | `100000128815` |
| Version list | `Annapurna:1.6.6;XEP:3.4.6;X4C51:2.0.0:DSPlibs-target:1.6.7` |

System information, sensor mode, profile ID, raw RF, downconverted IQ, reopen, and the documented X4Driver getters were observed. The configured X4Driver values were FPS 0, iterations 16, pulses per step 300, DAC 949 to 1100, TX power 2, downconversion off, 846 bins, frame area approximately -0.4373 to 5.0025 m, offset 0.18 m, center band 3, and PRF divider 16.

Application getters require a loaded profile on this firmware. With profile ID 0, sensitivity and TX-frequency getters return firmware error 1; several other application getters do not reply. The corrected version-list request at `0x07` passed on 2026-07-14. MXS records probe failures by category and does not infer support from product identity.

The sources declare extended-respiration feature ID `0x2375A16B` but define no command producer, APPDATA layout, parser, or usage example. MXS classifies the feature as firmware-unsupported and rejects set, get, debug-set, and debug-get operations before transmission. The identifier remains public so applications can recognize the known feature without implying support.

Periodic noisemap storage, XEP normalization/phase-noise/decimation/number-format/legacy-output controls, and X4Driver I2C access appear in public host headers but have no command producer in the checked-in target source. They raise `UnsupportedFirmwareError` rather than emitting guessed bytes.

The 2026-07-15 device suite observed sleep, respiration, and baseband-IQ messages from `ProfileId.RESPIRATION_2`. Baseband IQ and amplitude/phase state was queried from the device before and after changes because those outputs are mutually exclusive. Capability booleans for extended respiration and periodic noisemap storage are therefore `False`, not unknown.
