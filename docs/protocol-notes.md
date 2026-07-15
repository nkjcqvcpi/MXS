# Protocol Notes and Local-Source Ambiguities

## DataFloat count handling

`protocol_target.c:createDataFloatCommand` and
`createDataFloatCommandNoEscape` place a 32-bit little-endian sample count at
offset 10 when data is present. The older
`protocol_host_parser.c:parse_data_float` starts sample data at offset 14 but
derives the sample count from the remaining byte count instead of validating
the declared field. This implementation follows the target producer layout and
strictly validates the declared count. A ten-byte, zero-sample classic packet is
also accepted because the target omits the count when `length == 0`.

## No-escape checksum

The target no-escape builders emit a zero checksum byte after the length. The
host parser labels it unused and performs no integrity check. This
implementation skips that field and validates the packet boundary and inner
message lengths.

## Reply element counts and producer inconsistency

The field after `info` is an element count, not a byte count. The byte length is
`element_count * element_size`. The target integer producer omits the trailing
element-size byte, while byte, string, and float producers append it. MXS uses
the datatype size, accepts the integer variant with or without the trailing
size, and rejects ambiguous lengths. Empty integer replies may omit count and
size; other typed empty replies carry their size byte.

Live replies from Annapurna 1.6.6 use content ID zero for sensor-mode and output-control getters. This observation takes precedence over the absent callback in the checked-in XEP target application. MXS 0.2.3 does not retain traffic captures because pytest must obtain every device response from the connected module.

## Baseband APPDATA structure sizing

The host parser compares wire lengths with `sizeof(BasebandApData)`, a C struct
that contains pointers and may include ABI padding. That value is not a wire
format size. The target builders establish the actual 29-byte fixed header,
followed by `num_bins` I floats and `num_bins` Q floats. The Python parser uses
the target layout.

## SleepStatus checksum terminology

The plan calls the XOR field a CRC. The local implementation is bytewise XOR,
initialized with `0x7d`, rather than a polynomial CRC. Public counters retain
the plan's `crc_errors` name for compatibility, while documentation calls it a
checksum.

## Licensing scope

The MCP wrapper is MIT licensed. This project expresses the wire protocol
independently and includes the upstream copyright and license in `NOTICE.md`.
