import os
import resource
import sys
import threading
import time
from pathlib import Path

import pytest

from mxs import X4M200, X4Config
from mxs.recording import WireRecorder


@pytest.mark.hardware
@pytest.mark.soak
@pytest.mark.timeout(1900)
def test_thirty_minute_soak(tmp_path: Path) -> None:
    duration = float(os.getenv("MXS_SOAK_SECONDS", "1800"))
    started = time.monotonic()
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    initial_memory = usage_before.ru_maxrss
    initial_threads = threading.active_count()
    received = 0
    path = tmp_path / "soak.mcpbin"
    with (
        WireRecorder(path, os.environ["MXS_TEST_PORT"], 115200) as recorder,
        X4M200(
            port=os.environ["MXS_TEST_PORT"],
            frame_queue_size=256,
            raw_chunk_callback=recorder.write_chunk,
        ) as radar,
    ):
        radar.configure(X4Config())
        radar.start()
        while time.monotonic() - started < duration:
            radar.read_frame(timeout=2.0)
            received += 1
        stats = radar.statistics()
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    final_memory = usage_after.ru_maxrss
    memory_scale = 1 if sys.platform == "darwin" else 1024
    memory_growth_bytes = (final_memory - initial_memory) * memory_scale
    elapsed = time.monotonic() - started
    cpu_seconds = (usage_after.ru_utime + usage_after.ru_stime) - (
        usage_before.ru_utime + usage_before.ru_stime
    )
    print(
        {
            "elapsed_seconds": elapsed,
            "wire_bytes": recorder.bytes_written,
            "received_frames": received,
            "frame_gaps": stats.frame_counter_gaps,
            "checksum_errors": stats.crc_errors,
            "malformed_packets": stats.malformed_packets,
            "maximum_control_latency_seconds": stats.maximum_command_latency_seconds,
            "consumer_queue_high_water_mark": stats.queue_high_water_mark,
            "decoder_control_high_water_mark": stats.decoder_control_high_water_mark,
            "decoder_stream_high_water_mark": stats.decoder_stream_high_water_mark,
            "raw_callback_high_water_mark": stats.raw_callback_high_water_mark,
            "recorder_high_water_mark": recorder.queue_high_water_mark,
            "recorder_backlog_at_close": recorder.backlog,
            "memory_growth_mib": memory_growth_bytes / (1024 * 1024),
            "thread_count_before": initial_threads,
            "thread_count_after": threading.active_count(),
            "cpu_utilization": cpu_seconds / elapsed,
        }
    )
    assert received > duration * 10
    assert recorder.bytes_written > 0
    assert stats.crc_errors == 0
    assert stats.malformed_packets == 0
    assert stats.frame_counter_gaps == 0
    assert stats.consumer_drops == 0
    assert stats.queue_high_water_mark < 64
    assert stats.decoder_stream_high_water_mark < 64
    assert stats.raw_callback_high_water_mark < 64
    assert recorder.queue_high_water_mark < 64
    assert recorder.backlog == 0
    assert memory_growth_bytes < 128 * 1024 * 1024
    assert threading.active_count() <= initial_threads
