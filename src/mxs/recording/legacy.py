"""Narrow XTAN-05 compatibility for X4M200 baseband ``.dat`` files.

XTAN-05 documents field order but defines no magic number, endianness marker,
or general record envelope.  This module therefore supports only the two
baseband formats whose record boundaries are self-describing through
``NumOfBins``.  Other legacy record types are rejected rather than guessed.
"""

import struct
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from ..constants import CONTENT_ID_BASEBAND_AP, CONTENT_ID_BASEBAND_IQ
from ..models import BasebandAmplitudePhaseMessage, BasebandIqMessage

_HEADER = struct.Struct("<IIffff")


def read_baseband_iq(path: Path) -> Iterator[BasebandIqMessage]:
    with path.open("rb") as source:
        while header := source.read(_HEADER.size):
            if len(header) != _HEADER.size:
                raise ValueError("truncated XTAN-05 baseband-IQ header")
            counter, bins, bin_length, sample_frequency, carrier_frequency, offset = _HEADER.unpack(
                header
            )
            data = source.read(bins * 8)
            if len(data) != bins * 8:
                raise ValueError("truncated XTAN-05 baseband-IQ samples")
            values = np.frombuffer(data, dtype="<f4", count=bins * 2)
            iq = np.empty(bins, dtype=np.complex64)
            iq.real = values[:bins]
            iq.imag = values[bins:]
            yield BasebandIqMessage(
                CONTENT_ID_BASEBAND_IQ,
                counter,
                bins,
                bin_length,
                sample_frequency,
                carrier_frequency,
                offset,
                iq,
            )


def read_baseband_ap(path: Path) -> Iterator[BasebandAmplitudePhaseMessage]:
    with path.open("rb") as source:
        while header := source.read(_HEADER.size):
            if len(header) != _HEADER.size:
                raise ValueError("truncated XTAN-05 amplitude/phase header")
            counter, bins, bin_length, sample_frequency, carrier_frequency, offset = _HEADER.unpack(
                header
            )
            data = source.read(bins * 8)
            if len(data) != bins * 8:
                raise ValueError("truncated XTAN-05 amplitude/phase samples")
            values = np.frombuffer(data, dtype="<f4", count=bins * 2)
            yield BasebandAmplitudePhaseMessage(
                CONTENT_ID_BASEBAND_AP,
                counter,
                bins,
                bin_length,
                sample_frequency,
                carrier_frequency,
                offset,
                values[:bins].copy(),
                values[bins:].copy(),
            )


def read_legacy(path: Path, record_type: str):
    readers = {"baseband-iq": read_baseband_iq, "baseband-ap": read_baseband_ap}
    try:
        return readers[record_type](path)
    except KeyError as error:
        raise NotImplementedError(
            f"legacy record type {record_type!r} is not reliably self-delimiting"
        ) from error
