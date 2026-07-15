# Migrating from MXS 0.2.3 to 0.2.4

MXS 0.2.4 preserves the public API and tightens concurrency, cleanup, and firmware-state guarantees.

Every structured command now acquires `DeviceSession.operation_lock`. Applications may continue to compose calls normally. Multi-command SDK operations retain the same reentrant lock across the complete transaction, so concurrent callers cannot interleave acknowledgements or filesystem chunks.

Enabling a member of an exclusive output pair can now raise `InvalidDeviceStateError` before the set command is sent. Disable the active peer explicitly, then enable the requested output. The decision uses fresh device queries rather than the local cache.

Automatic baud detection now propagates cleanup failures even if the involved workers eventually terminate. Code that previously observed a later baud probe may instead receive the original callback, recorder, decoder, or shutdown exception. Close the session and correct that failure before retrying.

The tested Annapurna 1.6.6 application getters return content ID zero for several typed replies. MXS now validates the observed identifier. No application code change is required.

The hardware test suite records the initial profile and supported output states. Stateful tests restore them in `finally`, then enforce STOP at 115200 baud and verify that no MXS worker remains.
