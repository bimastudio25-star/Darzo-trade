from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dazro_trade.analysis.strategy_2_statistical_samples import render_statistical_sample_markdown


def render_research_doc(summary: dict[str, Any]) -> str:
    base = render_statistical_sample_markdown(summary)
    lines = [
        "# Strategy 2 Statistical Sample Recorder",
        "",
        "## Context",
        "",
        "Previous Strategy 2 diagnostics showed the current implementation was misaligned with the written Liquidity Expansion Model. A naive global Max Excursion profile produced unrealistic 200+ USD stops, which is not the intended workflow.",
        "",
        "This branch rebuilds the statistical sample collection process only. It does not deploy a strategy and does not change runtime behavior.",
        "",
        "## Corrected Interpretation",
        "",
        "- M15 x:45 means the candle whose open minute is 45 inside each H1 hour, not one fixed daily 00:45 candle.",
        "- A valid sample is an H1 context that manipulates beyond the H1 liquidity level and then distributes in the opposite direction.",
        "- Valid no-entry samples still count toward MAE if manipulation was smaller than the current average MAE.",
        "- MAE is the average manipulation depth among valid samples.",
        "- Risky SL is max manipulation among valid samples.",
        "- Conservative SL is max manipulation * 1.25.",
        "- TPs are quartiles of expansion projected from the H1 liquidity level, not from entry.",
        "- BE after TP1 remains a model rule, but this recorder does not simulate live management.",
        "",
        "## Safety",
        "",
        "- Strategy 3 untouched.",
        "- data/XAUUSD/*.csv untouched.",
        "- No live trading.",
        "- No Telegram.",
        "- No broker execution.",
        "- No order_send.",
        "- No orders.",
        "- Research-only.",
        "",
        "## Method",
        "",
        "- Evaluate previous H1 and deterministic dominant H1 references.",
        "- Select the M15 x:45 candle by timestamp minute == 45 inside each H1 hour.",
        "- Invalidate LONG if M15 x:45 high is taken before the H1 low sweep.",
        "- Invalidate SHORT if M15 x:45 low is taken before the H1 high sweep.",
        "- Measure manipulation depth from the H1 liquidity level before distribution.",
        "- Include valid no-entry samples in the MAE dataset.",
        "- Measure expansion from the H1 liquidity level after sweep.",
        "- Produce quartile TP and R:R diagnostics without optimization.",
        "",
        "## Results",
        "",
        base.split("## Results", 1)[1] if "## Results" in base else base,
        "",
        "## Unit Conversion",
        "",
        f"- price distance and USD distance are the same XAUUSD price movement in this report.",
        f"- pips are reported separately using pip_factor `{summary.get('pip_factor')}`.",
        "",
        "## Raw Summary JSON",
        "",
        "```json",
        json.dumps(
            {
                "h1_contexts_analyzed": summary.get("h1_contexts_analyzed"),
                "valid_samples": summary.get("valid_samples"),
                "valid_triggered_samples": summary.get("valid_triggered_samples"),
                "valid_no_entry_samples": summary.get("valid_no_entry_samples"),
                "status_counts": summary.get("status_counts"),
                "verdict_flags": summary.get("verdict_flags"),
            },
            indent=2,
            sort_keys=True,
        ),
        "```",
        "",
        "## Next Step",
        "",
        "Recommended Strategy 2-only next branch: `feat/strategy-2-manual-sample-label-pack` if manual chart review is needed, or `feat/strategy-2-reaction-confirmation-model` if the reaction proxy needs refinement.",
    ]
    return "\n".join(str(line) for line in lines) + "\n"


def write_research_doc(summary: dict[str, Any], docs_path: Path) -> str:
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    docs_path.write_text(render_research_doc(summary), encoding="utf-8")
    return str(docs_path)


__all__ = ["render_research_doc", "write_research_doc"]
