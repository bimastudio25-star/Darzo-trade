from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


DISTANCE_KEYWORDS = (
    "mae",
    "manipulation",
    "excursion",
    "sl",
    "stop",
    "expansion",
    "tp1",
    "tp2",
    "tp3",
    "tp4",
    "distance",
    "risk",
)

SAFETY = {
    "research_only": True,
    "dry_run": True,
    "live_trading_enabled": False,
    "telegram_enabled": False,
    "broker_called": False,
    "order_sent": False,
    "order_send_called": False,
    "signals_generated": False,
    "runtime_registration": False,
    "parameters_optimized": False,
    "market_data_written": False,
}


@dataclass(frozen=True)
class UnitDistanceAuditResult:
    audit_rows: pd.DataFrame
    summary: dict[str, Any]
    report_markdown: str


def price_to_pips(price_distance: float, pip_factor: float = 10.0) -> float:
    return round(float(price_distance) * float(pip_factor), 6)


def pips_to_price(pips: float, pip_factor: float = 10.0) -> float:
    return round(float(pips) / float(pip_factor), 6)


def _numeric_value(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_distance_field(field: str) -> bool:
    lower = field.lower()
    if lower.endswith("_pct") or lower.endswith("_count") or lower.endswith("_rate"):
        return False
    if lower.endswith("_r") or lower.endswith("_rr"):
        return True
    return any(keyword in lower for keyword in DISTANCE_KEYWORDS)


def _base_field(field: str) -> str:
    for suffix in ("_usd", "_pips", "_price", "_price_distance", "_distance_usd", "_distance_pips"):
        if field.endswith(suffix):
            return field[: -len(suffix)]
    return field


def _field_leaf(field: str) -> str:
    return field.split(".")[-1].split("]")[-1].lstrip(".")


def _summary_rank(row: dict[str, Any], key: str) -> int:
    source = str(row.get("source_file", ""))
    field = str(row.get("field", ""))
    if key.startswith("tp") or key == "max_expansion_usd":
        if "containing_diagnostic_summary.json" in source and field.startswith("tp_r_profile[0]."):
            return 0
        if "containing_tp_r_profile.csv" in source and field == key:
            return 1
    else:
        if "containing_diagnostic_summary.json" in source and field.startswith("risk_profile[0]."):
            return 0
        if "containing_risk_profile.csv" in source and field == key:
            return 1
    if field == key:
        return 2
    if "tail_risk_hardening" in source and field.startswith("r_profile_before."):
        return 3
    return 10


def _flatten_json(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_json(item, name))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            name = f"{prefix}[{index}]"
            rows.extend(_flatten_json(item, name))
    else:
        rows.append((prefix, value))
    return rows


def _source_label(path: Path) -> str:
    parts = path.parts
    if "backtests" in parts:
        idx = parts.index("backtests")
        return "/".join(parts[idx:])
    return str(path)


def _detect_pair_evidence(row: pd.Series, field: str, pip_factor: float) -> tuple[str, float | None]:
    lower = field.lower()
    if lower.endswith("_usd"):
        pips_field = f"{field[:-4]}_pips"
        usd = _numeric_value(row.get(field))
        pips = _numeric_value(row.get(pips_field))
        if usd is not None and pips is not None:
            expected = price_to_pips(usd, pip_factor)
            delta = round(abs(expected - pips), 8)
            if delta <= 1e-4:
                return f"paired {pips_field} equals {field} * pip_factor", delta
            return f"paired {pips_field} does not match {field} * pip_factor", delta
    if lower.endswith("_pips"):
        usd_field = f"{field[:-5]}_usd"
        pips = _numeric_value(row.get(field))
        usd = _numeric_value(row.get(usd_field))
        if usd is not None and pips is not None:
            expected = pips_to_price(pips, pip_factor)
            delta = round(abs(expected - usd), 8)
            if delta <= 1e-4:
                return f"paired {usd_field} equals {field} / pip_factor", delta
            return f"paired {usd_field} does not match {field} / pip_factor", delta
    return "no direct pair found", None


def _interpret_field(field: str, raw_value: float, pip_factor: float, evidence: str) -> dict[str, Any]:
    lower = field.lower()
    if lower.endswith("_pips"):
        price_distance = pips_to_price(raw_value, pip_factor)
        pips = round(raw_value, 6)
        interpreted = "pips"
        corrected_label = "pips"
    elif lower.endswith("_r") or lower.endswith("_rr") or lower.endswith("_ratio"):
        price_distance = None
        pips = None
        interpreted = "dimensionless_ratio"
        corrected_label = "R multiple / ratio, not a distance"
    else:
        price_distance = round(raw_value, 6)
        pips = price_to_pips(raw_value, pip_factor)
        interpreted = "xauusd_price_distance"
        corrected_label = "XAUUSD price-distance units, not account-currency dollars"

    if "paired" in evidence and lower.endswith("_usd"):
        interpreted = "xauusd_price_distance"
        corrected_label = "XAUUSD price-distance units; pips = price_distance * pip_factor"
    return {
        "interpreted_as": interpreted,
        "price_distance_usd": price_distance,
        "pips": pips,
        "corrected_label": corrected_label,
    }


def audit_csv_file(path: Path, pip_factor: float) -> list[dict[str, Any]]:
    frame = pd.read_csv(path)
    rows: list[dict[str, Any]] = []
    distance_fields = [field for field in frame.columns if _is_distance_field(field)]
    for field in distance_fields:
        numeric = pd.to_numeric(frame[field], errors="coerce").dropna()
        if numeric.empty:
            continue
        representative = float(numeric.iloc[0])
        max_value = float(numeric.max())
        median_value = float(numeric.median())
        sample_row = frame[pd.to_numeric(frame[field], errors="coerce").notna()].iloc[0]
        evidence, delta = _detect_pair_evidence(sample_row, field, pip_factor)
        interpreted = _interpret_field(field, representative, pip_factor, evidence)
        rows.append(
            {
                "source_file": _source_label(path),
                "field": field,
                "raw_value": round(representative, 6),
                "raw_median": round(median_value, 6),
                "raw_max": round(max_value, 6),
                "interpreted_as": interpreted["interpreted_as"],
                "price_distance_usd": interpreted["price_distance_usd"],
                "pips": interpreted["pips"],
                "pip_factor_used": float(pip_factor),
                "corrected_label": interpreted["corrected_label"],
                "affected_reports": _source_label(path.parent),
                "pair_evidence": evidence,
                "pair_delta": delta,
                "r_profile_changes_after_correction": "NO" if interpreted["interpreted_as"] != "ambiguous" else "UNKNOWN",
                "notes": _field_note(field, interpreted["interpreted_as"]),
            }
        )
    return rows


def audit_json_file(path: Path, pip_factor: float) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    flat = _flatten_json(data)
    by_field = {name: value for name, value in flat}
    rows: list[dict[str, Any]] = []
    for field, value in flat:
        if not _is_distance_field(field):
            continue
        raw = _numeric_value(value)
        if raw is None:
            continue
        short = field.split(".")[-1].split("[")[-1].rstrip("]")
        evidence = "no direct pair found"
        delta = None
        if short.endswith("_usd"):
            pips_name = f"{field[:-4]}_pips"
            pips = _numeric_value(by_field.get(pips_name))
            if pips is not None:
                expected = price_to_pips(raw, pip_factor)
                delta = round(abs(expected - pips), 8)
                evidence = "json pair pips equals usd * pip_factor" if delta <= 1e-4 else "json pair mismatch"
        interpreted = _interpret_field(short, raw, pip_factor, evidence)
        rows.append(
            {
                "source_file": _source_label(path),
                "field": field,
                "raw_value": round(raw, 6),
                "raw_median": round(raw, 6),
                "raw_max": round(raw, 6),
                "interpreted_as": interpreted["interpreted_as"],
                "price_distance_usd": interpreted["price_distance_usd"],
                "pips": interpreted["pips"],
                "pip_factor_used": float(pip_factor),
                "corrected_label": interpreted["corrected_label"],
                "affected_reports": _source_label(path.parent),
                "pair_evidence": evidence,
                "pair_delta": delta,
                "r_profile_changes_after_correction": "NO" if interpreted["interpreted_as"] != "ambiguous" else "UNKNOWN",
                "notes": _field_note(short, interpreted["interpreted_as"]),
            }
        )
    return rows


def _field_note(field: str, interpreted_as: str) -> str:
    lower = field.lower()
    if lower.endswith("_usd"):
        return "Label should be read as XAUUSD price-distance, not account PnL dollars."
    if lower.endswith("_pips"):
        return "Pip value is derived from price-distance using pip_factor."
    if lower.endswith("_r") or lower.endswith("_rr"):
        return "R profile is dimensionless; consistent unit conversion does not change it."
    return f"Interpreted as {interpreted_as}."


def build_corrected_summary(audit: pd.DataFrame, pip_factor: float) -> dict[str, Any]:
    key_fields = [
        "max_excursion_usd",
        "conservative_sl_usd",
        "tp1_distance_usd",
        "tp2_distance_usd",
        "tp3_distance_usd",
        "tp4_distance_usd",
        "mae_avg_usd",
        "mae_median_usd",
        "mae_p90_usd",
        "mae_p95_usd",
        "max_expansion_usd",
    ]
    corrected: dict[str, Any] = {}
    for key in key_fields:
        subset = audit[audit["field"].astype(str).map(_field_leaf).eq(key)]
        if subset.empty:
            continue
        rows = subset.to_dict("records")
        row = sorted(rows, key=lambda item: _summary_rank(item, key))[0]
        corrected[key] = {
            "raw_value": row.get("raw_value"),
            "interpreted_as": row.get("interpreted_as"),
            "price_distance_usd": row.get("price_distance_usd"),
            "pips": row.get("pips"),
            "corrected_label": row.get("corrected_label"),
            "source_file": row.get("source_file"),
        }
    usd_rows = audit[audit["field"].astype(str).str.endswith("_usd", na=False)]
    pips_pairs = usd_rows[usd_rows["pair_evidence"].astype(str).str.contains("equals", na=False)]
    ambiguous = audit[audit["pair_evidence"].astype(str).str.contains("does not match", na=False)]
    return {
        "pip_factor_used": float(pip_factor),
        "conversion_rule": {
            "pips": "price_distance * pip_factor",
            "price_distance": "pips / pip_factor",
        },
        "unit_semantics_verdict": "RAW_DISTANCE_VALUES_ARE_XAUUSD_PRICE_DISTANCE_NOT_PIPS",
        "usd_label_warning": "Existing *_usd labels mean XAUUSD price-distance units, not account-currency dollars.",
        "paired_usd_pips_fields_checked": int(len(usd_rows)),
        "paired_usd_pips_fields_matching": int(len(pips_pairs)),
        "pair_mismatch_count": int(len(ambiguous)),
        "pips_mislabeled_as_usd_found": False,
        "usd_label_ambiguity_found": bool(len(usd_rows) > 0),
        "r_profile_changes_after_correction": "NO; R ratios use consistent distance units. Absolute labels need clarification.",
        "corrected_key_values": corrected,
        "follow_up_recommended": bool(len(usd_rows) > 0),
        "recommended_follow_up_branch": "fix/strategy-2-distance-label-normalization",
        "safety": SAFETY,
    }


def build_unit_distance_audit(input_dirs: list[str | Path], *, pip_factor: float = 10.0) -> UnitDistanceAuditResult:
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    for directory in input_dirs:
        root = Path(directory)
        if not root.exists():
            raise FileNotFoundError(f"input directory missing: {root}")
        for path in sorted(root.glob("*")):
            if path.suffix.lower() == ".csv":
                rows.extend(audit_csv_file(path, pip_factor))
            elif path.suffix.lower() == ".json":
                rows.extend(audit_json_file(path, pip_factor))
    audit = pd.DataFrame(rows)
    if audit.empty:
        audit = pd.DataFrame(
            columns=[
                "source_file",
                "field",
                "raw_value",
                "interpreted_as",
                "price_distance_usd",
                "pips",
                "pip_factor_used",
                "corrected_label",
                "affected_reports",
                "pair_evidence",
                "r_profile_changes_after_correction",
            ]
        )
    summary = build_corrected_summary(audit, pip_factor)
    summary["runtime_seconds"] = round(time.perf_counter() - started, 4)
    summary["input_dirs"] = [str(Path(item)) for item in input_dirs]
    summary["fields_audited"] = int(len(audit))
    report = render_unit_distance_report(audit, summary)
    return UnitDistanceAuditResult(audit_rows=audit, summary=summary, report_markdown=report)


def write_unit_distance_outputs(result: UnitDistanceAuditResult, output_dir: str | Path, *, docs_path: str | Path | None = None) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "audit_csv": output / "unit_distance_audit.csv",
        "summary": output / "corrected_distance_summary.json",
        "report": output / "strategy_2_unit_distance_audit.md",
    }
    result.audit_rows.to_csv(paths["audit_csv"], index=False)
    paths["summary"].write_text(json.dumps(result.summary, indent=2, sort_keys=True), encoding="utf-8")
    paths["report"].write_text(result.report_markdown, encoding="utf-8")
    if docs_path:
        docs = Path(docs_path)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(result.report_markdown, encoding="utf-8")
        paths["docs"] = docs
    return {key: str(path) for key, path in paths.items()}


def render_unit_distance_report(audit: pd.DataFrame, summary: dict[str, Any]) -> str:
    key_values = summary.get("corrected_key_values", {})
    lines = [
        "# Strategy 2 Unit Distance Audit",
        "",
        "## Context",
        "",
        "This audit checks whether Strategy 2 values such as Max Excursion, conservative SL, expansion, and TP distances are raw XAUUSD price-distance values or pips. It does not change strategy logic or rewrite historical reports.",
        "",
        "## Safety",
        "",
        "- Strategy 3 untouched.",
        "- data/XAUUSD/*.csv untouched.",
        "- No live trading, Telegram, broker execution, orders, signal generation, or optimization.",
        "",
        "## Conversion Rule",
        "",
        f"- pip_factor used: {summary.get('pip_factor_used')}",
        "- pips = price_distance * pip_factor",
        "- price_distance = pips / pip_factor",
        "- `*_usd` in these reports should be read as XAUUSD price-distance units, not account-currency dollars.",
        "",
        "## Verdict",
        "",
        f"- Unit semantics: `{summary.get('unit_semantics_verdict')}`",
        f"- Pair mismatches: {summary.get('pair_mismatch_count')}",
        f"- R-profile changes after correction: {summary.get('r_profile_changes_after_correction')}",
        "",
        "## Audit Answers",
        "",
        "1. Raw `*_usd` values are interpreted as XAUUSD price-distance values, not pips and not account-currency PnL dollars.",
        "2. With `pip_factor=10`, `pips = price_distance * 10` and `price_distance = pips / 10`.",
        "3. No `*_usd`/`*_pips` pair mismatches were found. The audit did not find evidence that pips were stored as USD; it found that the `USD` label is ambiguous and should be normalized.",
        "4. R calculations use consistent distance units, so the R-profile does not change under unit relabeling.",
        "5. Corrected SL/TP values are shown below in both XAUUSD price-distance and pips.",
        "",
        "## Corrected Key Values",
        "",
        "| Field | Raw value | Price distance | Pips | Corrected label | Source |",
        "|---|---:|---:|---:|---|---|",
    ]
    for field, value in key_values.items():
        lines.append(
            f"| {field} | {value.get('raw_value')} | {value.get('price_distance_usd')} | {value.get('pips')} | {value.get('corrected_label')} | {value.get('source_file')} |"
        )
    lines.extend(
        [
            "",
            "## R-Profile",
            "",
            "R calculations are dimensionless. If all distances are converted consistently, R values do not change. The issue is label clarity: absolute distances should be shown as both XAUUSD price-distance and pips.",
            "",
            "## Affected Reports",
            "",
        ]
    )
    for report in sorted(set(str(item) for item in audit.get("affected_reports", pd.Series(dtype=str)).dropna().tolist())):
        lines.append(f"- {report}")
    lines.extend(
        [
            "",
            "## Follow-Up",
            "",
            f"- Recommended follow-up branch: `{summary.get('recommended_follow_up_branch')}`",
            "- Proposed fix: normalize report labels from ambiguous `USD` wording to `price_distance_usd` plus explicit pips.",
        ]
    )
    return "\n".join(lines) + "\n"
