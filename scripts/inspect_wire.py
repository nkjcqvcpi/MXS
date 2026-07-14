import argparse
from pathlib import Path

from mxs.framing import McpStreamDecoder
from mxs.messages import decode_message
from mxs.recording import replay_wire

parser = argparse.ArgumentParser()
parser.add_argument("path", type=Path)
args = parser.parse_args()
decoder = McpStreamDecoder()
for chunk in replay_wire(args.path):
    for payload in decoder.feed(chunk):
        print(decode_message(payload))
