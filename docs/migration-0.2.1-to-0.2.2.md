# Migration from MXS 0.2.1 to 0.2.2

MXS 0.2.2 preserves the public acquisition API but tightens several behavioral contracts. Automatic baud detection now discards all runtime objects after a failed candidate, so a timeout at 115200 cannot poison a subsequent 921600 probe. Closing a device or recorder may still raise the first shutdown error, but all owned state is cleared before that error reaches the caller.

The legacy `raw_chunk_callback` again receives only bytes read from the module. Code that needs transmitted commands must use `wire_chunk_callback`, whose `WireChunk.direction` distinguishes RX from TX.

Unsafe operations now query the module's sensor mode after checking their environment gate. Most require STOP. Frame injection and raw register writes also permit MANUAL because the checked-in XEP workflow defines those operations in manual mode. An OPEN host session is no longer sufficient evidence that firmware is stopped.

All filesystem methods on a session share one lock. A read cannot interleave with a multi-command create, write, and commit transaction, and failed writes attempt an aborting close before preserving the original exception.

`ProfileId.SLEEP` now has the Legacy-SW value `0x00F17B17`. `ProfileId.RESPIRATION_2` remains `0x064E57AD`; applications that used `SLEEP` as an accidental alias for that value must select `RESPIRATION_2` explicitly.

The local sources declare extended-respiration feature ID `0x2375A16B` but contain no target producer, parser, data structure, or example that defines its payload. MXS does not decode this identifier without an authoritative wire layout.
