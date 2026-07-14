# Migration from MXS 0.2.0 to 0.2.1

MXS 0.2.1 removes the deprecated compatibility package and command alias. Import `mxs`, invoke `mxs`, and use only `MXS_` environment variables.

Every uncorrelated command timeout now closes the transport and requires `recover()`. Code that previously retried a getter on the same session must recover first. `stop()` does not clear this condition.

`IoPinSetup` is a bit flag and `IoPinFeature` is a mutually exclusive enum. `get_iopin_control()` returns those typed values. Noisemap store and deletion require `MXS_ENABLE_NOISEMAP_FLASH_WRITE=1` and a non-streaming healthy state.

Wire recording accepts `WireChunk` values with an I/O-boundary timestamp and RX/TX direction. The byte-only raw callback remains available for passive inspection, but recorders should use `wire_chunk_callback`.

Downconverted `DataFloat` messages are published on `messages.raw_iq`; `messages.raw_rf` is restricted to RF data.
