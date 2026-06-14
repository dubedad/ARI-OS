"""Render TrendSignals to markdown + write under the ARI-OS state home."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Iterable

from ari_os.tools.cortex.config import state_home
from ari_os.tools.cortex.predictive.trend import TrendSignal


def render_signals_md(signals: Iterable[TrendSignal]) -> str:
    """Render a list of TrendSignals as a markdown block."""
    signals = list(signals)
    if not signals:
        return "## Predictive signals\n\n_No signals at this run._\n"
    lines = ["## Predictive signals", ""]
    for s in signals:
        days = s.window_seconds // 86400
        lines.append(
            f"### Cluster {s.cluster_id} — grew {s.growth_ratio:.2f}x in ~{days}d"
        )
        lines.append(
            f"- Old size: {s.old_size} → new size: {s.new_size}"
        )
        if s.sample_chunk_ids:
            ids = ", ".join(str(c) for c in s.sample_chunk_ids)
            lines.append(f"- Sample chunk ids: {ids}")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_signals(
    signals: Iterable[TrendSignal],
    out_dir: Path | None = None,
    date_str: str | None = None,
) -> Path:
    """Append a rendered signals block to <out_dir>/<YYYY-MM-DD>.md (append-only).

    Defaults to ``<ARI_OS_HOME>/predictive_signals/``.
    """
    if out_dir is None:
        out_dir = state_home() / "predictive_signals"
    out_dir.mkdir(parents=True, exist_ok=True)
    if date_str is None:
        date_str = dt.datetime.now().strftime("%Y-%m-%d")
    path = out_dir / f"{date_str}.md"
    rendered = render_signals_md(signals)
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    block = f"<!-- emitted at {ts} -->\n{rendered}\n"
    with path.open("a") as f:
        f.write(block)
    return path
