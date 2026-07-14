"""Thread-safe counters and passive diagnostic helpers."""

from threading import Lock

from .models import SessionStatistics


class StatisticsTracker:
    def __init__(self) -> None:
        self._lock = Lock()
        self._values: dict[str, int | float] = {
            "bytes_received": 0,
            "bytes_transmitted": 0,
            "classic_packets": 0,
            "noescape_packets": 0,
            "crc_errors": 0,
            "malformed_packets": 0,
            "unknown_packets": 0,
            "commands_sent": 0,
            "ack_count": 0,
            "firmware_errors": 0,
            "command_timeouts": 0,
            "frames_received": 0,
            "frame_counter_gaps": 0,
            "consumer_drops": 0,
            "queue_overflows": 0,
            "queue_high_water_mark": 0,
            "maximum_command_latency_seconds": 0.0,
        }

    def add(self, name: str, amount: int = 1) -> None:
        with self._lock:
            value = self._values[name]
            self._values[name] = value + amount

    def maximum(self, name: str, value: int | float) -> None:
        with self._lock:
            self._values[name] = max(self._values[name], value)

    def snapshot(self) -> SessionStatistics:
        with self._lock:
            v = self._values
            return SessionStatistics(
                bytes_received=int(v["bytes_received"]),
                bytes_transmitted=int(v["bytes_transmitted"]),
                classic_packets=int(v["classic_packets"]),
                noescape_packets=int(v["noescape_packets"]),
                crc_errors=int(v["crc_errors"]),
                malformed_packets=int(v["malformed_packets"]),
                unknown_packets=int(v["unknown_packets"]),
                commands_sent=int(v["commands_sent"]),
                ack_count=int(v["ack_count"]),
                firmware_errors=int(v["firmware_errors"]),
                command_timeouts=int(v["command_timeouts"]),
                frames_received=int(v["frames_received"]),
                frame_counter_gaps=int(v["frame_counter_gaps"]),
                consumer_drops=int(v["consumer_drops"]),
                queue_overflows=int(v["queue_overflows"]),
                queue_high_water_mark=int(v["queue_high_water_mark"]),
                maximum_command_latency_seconds=float(v["maximum_command_latency_seconds"]),
            )
