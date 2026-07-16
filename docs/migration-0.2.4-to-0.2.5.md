# Migrating from MXS 0.2.4 to 0.2.5

MXS 0.2.5 preserves the public acquisition API and closes opening-time error races. `DeviceState.OPENING` is now observable while a baud candidate owns active workers. `open()` returns only after real traffic has decoded and routed, pre-acceptance callback work has completed, and every worker has passed its health check.

Reply expectations can admit a documented set of content IDs. This accommodates the source-defined identifier and Annapurna 1.6.6's observed identifier `0` without relaxing reply datatype, info, element count, element size, or payload length.

Normal and debug output controls now share the same exclusivity transaction. A conflicting enable raises `InvalidDeviceStateError` before the requested set command is transmitted. MXS then queries the complete group after an accepted set and raises `ProtocolError` if firmware reports more than one enabled member.

Unsupported XEP controls now expose explicit signatures. Positional and documented keyword forms raise `UnsupportedFirmwareError`; Python no longer raises an incidental `TypeError` before the firmware-support decision.

Profile restoration handles baseline ID `0` explicitly. MXS first verifies whether no profile is already loaded. If not, it uses the reset-and-reconnect behavior documented by the local X4M200 interface, then verifies profile ID `0` instead of guessing that `load_profile(0)` is an unload command.
