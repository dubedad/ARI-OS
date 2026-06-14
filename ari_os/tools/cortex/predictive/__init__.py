"""ARI-OS Cortex predictive layer — clustering, prefetch, and trend signals."""

from .clusterer import run_cluster_sweep
from .prefetch import past_chunks_for_cwd, prefetch_for_cwd
from .signal_writer import render_signals_md, write_signals
from .trend import TrendSignal, cluster_sizes_at, detect_growth_signals

__all__ = [
    "cluster_sizes_at",
    "detect_growth_signals",
    "past_chunks_for_cwd",
    "prefetch_for_cwd",
    "render_signals_md",
    "run_cluster_sweep",
    "TrendSignal",
    "write_signals",
]
