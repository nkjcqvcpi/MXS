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

## Reply short form

`protocol_host_parser.c:parse_reply` permits a short reply containing response
type, data type, content ID, info, and one trailing data-size byte. Longer
replies add a 32-bit byte length, data bytes, and a final data-size byte. The C
parser does not adequately bounds-check the latter form. The Python parser
supports both forms with strict bounds checks.

## Baseband APPDATA structure sizing

The host parser compares wire lengths with `sizeof(BasebandApData)`, a C struct
that contains pointers and may include ABI padding. That value is not a wire
format size. The target builders establish the actual 29-byte fixed header,
followed by `num_bins` I floats and `num_bins` Q floats. The Python parser uses
the target layout.

## SleepStatus fixture terminology

The plan calls the XOR field a CRC. The local implementation is bytewise XOR,
initialized with `0x7d`, rather than a polynomial CRC. Public counters retain
the plan's `crc_errors` name for compatibility, while documentation calls it a
checksum.

## Licensing scope

The MCP wrapper is MIT licensed. This project expresses the wire protocol
independently and includes the upstream copyright and license in `NOTICE.md`.

