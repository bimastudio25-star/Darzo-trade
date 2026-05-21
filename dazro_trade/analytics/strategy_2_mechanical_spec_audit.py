from __future__ import annotations

from pathlib import Path
from typing import Any

from dazro_trade.analysis.strategy_2_mechanical_spec import mechanical_report_markdown


def write_research_doc(summary: dict[str, Any], docs_path: str | Path) -> str:
    path = Path(docs_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mechanical_report_markdown(summary), encoding="utf-8")
    return str(path)

