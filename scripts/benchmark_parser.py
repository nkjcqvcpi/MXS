import argparse
import time
from pathlib import Path

from mxs.framing import McpStreamDecoder
from mxs.recording import replay_wire

parser = argparse.ArgumentParser()
parser.add_argument("path", type=Path)
parser.add_argument("--iterations", type=int, default=100)
parser.add_argument("--device-rate", type=float, default=921600 / 10)
args = parser.parse_args()
chunks = list(replay_wire(args.path))
byte_count = sum(map(len, chunks)) * args.iterations
started = time.perf_counter()
for _ in range(args.iterations):
    decoder = McpStreamDecoder()
    for chunk in chunks:
        decoder.feed(chunk)
elapsed = time.perf_counter() - started
rate = byte_count / elapsed
print(f"{byte_count} bytes in {elapsed:.3f}s: {rate:,.0f} bytes/s")
print(f"{rate / args.device_rate:.1f}x configured device byte rate")
raise SystemExit(0 if rate >= args.device_rate * 10 else 1)
