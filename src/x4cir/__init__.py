"""Compatibility namespace for MXS 0.1 imports.

New code should import :mod:`mxs`.  The compatibility package deliberately
exports only the 0.1 public surface; protocol internals were never public.
"""

from mxs import X4M200, AsyncX4M200, CirFrame, SessionStatistics, X4Config

__all__ = ["X4M200", "AsyncX4M200", "CirFrame", "SessionStatistics", "X4Config"]
