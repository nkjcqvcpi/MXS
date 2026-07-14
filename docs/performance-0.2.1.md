# MXS 0.2.1 performance validation

The 0.2.1 offline suite exercises bounded delivery, cancellation recovery, and parser throughput. Live performance evidence must be collected with the target device using the hardware and soak commands in `docs/hardware-debugging.md`.

The acceptance threshold is parser and decoder throughput above ten times observed device traffic, with no sustained queue growth, frame loss, recorder error, thread leak, or sustained memory growth. The run must report RX and TX bytes, per-stream gaps, queue high-water marks, maximum command latency, CPU utilization, memory growth, and final thread count.

No 0.2.0 soak result is reused as 0.2.1 evidence because the recorder timestamp, direction, async subscription, and frame-counter implementations changed.
