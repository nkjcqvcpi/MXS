# MXS 0.2.0 performance

Benchmarks ran on 2026-07-14 with Python 3.14.6 and real X4M200 wire recordings. The recordings were removed in 0.2.3 when pytest became hardware-only; this document retains the historical measurements, not reusable test inputs.

| Fixture | Bytes processed | Time | Throughput | Relative to 92,160 B/s |
|---|---:|---:|---:|---:|
| RF baseline, 100 replays | 34,417,900 | 3.388 s | 10,157,317 B/s | 110.2x |
| Sleep baseline, 100 replays | 40,000 | 0.005 s | 7,855,267 B/s | 85.2x |

Both framing results exceed the required tenfold device rate. The safe RF and IQ hardware tests reported zero unexplained checksum errors and no silent frame gaps.

## Hardware soak

The instrumented soak ran on `/dev/tty.usbmodem2101` for 1,800.24 seconds with raw wire recording enabled.

| Metric | Result |
|---|---:|
| Raw wire bytes | 104,479,134 |
| Received frames | 30,665 |
| Frame gaps | 0 |
| Checksum errors | 0 |
| Malformed packets | 0 |
| Consumer drops | 0 |
| Maximum control latency | 0.1374 s |
| Consumer queue high-water mark | 1 |
| Decoder control queue high-water mark | 1 |
| Decoder stream queue high-water mark | 1 |
| Raw callback queue high-water mark | 1 |
| Recorder queue high-water mark | 1 |
| Recorder backlog after close | 0 |
| Process memory growth | 0.8125 MiB |
| CPU utilization | 4.78% |
| Threads before and after | 1 and 1 |

The run had no silent loss, sustained backlog, worker failure, serial backlog, or shutdown leak.
