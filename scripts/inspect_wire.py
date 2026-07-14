import argparse
from pathlib import Path

from x4cir.framing import McpStreamDecoder
from x4cir.messages import decode_message
from x4cir.recording import replay_wire

parser = argparse.ArgumentParser()
parser.add_argument("path", type=Path)
args = parser.parse_args()
decoder = McpStreamDecoder()
for chunk in replay_wire(args.path):
    for payload in decoder.feed(chunk):
        print(decode_message(payload))
