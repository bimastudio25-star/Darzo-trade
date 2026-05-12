from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dazro_trade.core.symbols import price_to_pips


@dataclass(frozen=True)
class TargetPolicy:
    min_normal_reaction_target_pips: float = 50.0
    preferred_reaction_target_pips: float = 100.0
    allow_vwap_1r_target: bool = True
    min_vwap_target_pips: float = 30.0
    min_rr_normal: float = 1.5
    min_rr_vwap_scalp: float = 1.0


def build_intelligent_targets(
    *,
    symbol: str,
    direction: str,
    entry: float,
    stop: float,
    vwap_snapshot: dict | None = None,
    liquidity_pools: list[dict] | None = None,
    volume_profile: dict | None = None,
    max_r: int = 10,
) -> list[dict]:
    risk = abs(entry - stop)
    if risk <= 0:
        return []
    candidates: list[dict] = []
    sign = 1 if direction in {"LONG", "BUY"} else -1
    for multiple in range(1, max_r + 1):
        price = entry + sign * risk * multiple
        candidates.append(_target(symbol, f"{multiple}R", price, entry, risk, f"{multiple}R mathematical", "medium"))
    if vwap_snapshot:
        vwap = vwap_snapshot.get("vwap")
        if _is_ahead(direction, entry, vwap):
            candidates.append(_target(symbol, "VWAP", float(vwap), entry, risk, "VWAP", "high"))
        for key in ("upper_1", "upper_2", "lower_1", "lower_2"):
            level = vwap_snapshot.get(key)
            if _is_ahead(direction, entry, level):
                candidates.append(_target(symbol, key, float(level), entry, risk, f"VWAP {key}", "medium"))
    for pool in liquidity_pools or []:
        level = pool.get("level")
        if _is_ahead(direction, entry, level):
            candidates.append(_target(symbol, pool.get("pool_type", "liquidity"), float(level), entry, risk, "liquidity_pool", "high"))
    if volume_profile:
        for level in [volume_profile.get("poc"), *(volume_profile.get("hvn") or []), *(volume_profile.get("lvn") or [])]:
            if _is_ahead(direction, entry, level):
                candidates.append(_target(symbol, "volume_profile", float(level), entry, risk, "POC/HVN/LVN", "medium"))
        for low, high in volume_profile.get("volume_cracks") or []:
            boundary = low if direction in {"SHORT", "SELL"} else high
            if _is_ahead(direction, entry, boundary):
                candidates.append(_target(symbol, "volume_crack", float(boundary), entry, risk, "volume crack boundary", "medium"))
    dedup: dict[float, dict] = {}
    for item in candidates:
        key = round(item["price"], 2)
        old = dedup.get(key)
        if old is None or _quality_rank(item["quality"]) > _quality_rank(old["quality"]):
            dedup[key] = item
    ordered = sorted(dedup.values(), key=lambda item: item["distance_pips"])
    for idx, item in enumerate(ordered, start=1):
        item["label"] = f"TP{idx}"
    return ordered[:max_r]


def validate_target_space(
    symbol: str,
    direction: str,
    entry: float,
    stop: float,
    targets: list[dict],
    vwap_snapshot: dict | None,
    liquidity_pools: list[dict],
    config: TargetPolicy | Any | None = None,
) -> dict:
    policy = _policy(config)
    risk_pips = price_to_pips(symbol, abs(entry - stop))
    reason_codes: list[str] = []
    if risk_pips <= 0:
        return {"valid": False, "setup_target_type": "NO_CLEAN_TARGET", "target_pips": 0, "rr": 0, "target_price": None, "reason_codes": ["invalid_risk"]}
    clean_targets = [target for target in targets if target.get("distance_pips", 0) > 0 and _is_ahead(direction, entry, target.get("price"))]
    if not clean_targets:
        return {"valid": False, "setup_target_type": "NO_CLEAN_TARGET", "target_pips": 0, "rr": 0, "target_price": None, "reason_codes": ["no_clean_target_space_no_trade"]}
    if policy.allow_vwap_1r_target:
        for target in clean_targets:
            if target.get("basis") == "VWAP":
                target_pips = float(target["distance_pips"])
                rr = target_pips / risk_pips
                if target_pips >= policy.min_vwap_target_pips and rr >= policy.min_rr_vwap_scalp:
                    return {"valid": True, "setup_target_type": "VWAP_1R_SCALP", "target_pips": target_pips, "rr": round(rr, 2), "target_price": target["price"], "reason_codes": ["vwap_1r_target_valid"]}
    first = clean_targets[0]
    target_pips = float(first["distance_pips"])
    rr = target_pips / risk_pips
    if policy.allow_vwap_1r_target and first.get("basis") == "VWAP" and target_pips >= policy.min_vwap_target_pips and rr >= policy.min_rr_vwap_scalp:
        reason_codes.append("vwap_1r_target_valid")
        return {"valid": True, "setup_target_type": "VWAP_1R_SCALP", "target_pips": target_pips, "rr": round(rr, 2), "target_price": first["price"], "reason_codes": reason_codes}
    if target_pips < policy.min_normal_reaction_target_pips:
        reason_codes.append("target_space_below_minimum")
        return {"valid": False, "setup_target_type": "NO_CLEAN_TARGET", "target_pips": target_pips, "rr": round(rr, 2), "target_price": first["price"], "reason_codes": reason_codes}
    if rr < policy.min_rr_normal:
        reason_codes.append("rr_below_minimum_normal")
        return {"valid": False, "setup_target_type": "NO_CLEAN_TARGET", "target_pips": target_pips, "rr": round(rr, 2), "target_price": first["price"], "reason_codes": reason_codes}
    reason_codes.append("normal_reaction_target_50_100_pips_valid")
    if target_pips >= policy.preferred_reaction_target_pips:
        reason_codes.append("preferred_reaction_target_100_pips_available")
    return {"valid": True, "setup_target_type": "NORMAL_REACTION", "target_pips": target_pips, "rr": round(rr, 2), "target_price": first["price"], "reason_codes": reason_codes}


def _target(symbol: str, label: str, price: float, entry: float, risk: float, basis: str, quality: str) -> dict:
    distance = abs(price - entry)
    return {
        "label": label,
        "price": round(price, 2),
        "distance_pips": round(price_to_pips(symbol, distance), 1),
        "rr": round(distance / risk, 2) if risk else 0,
        "basis": basis,
        "quality": quality,
        "is_minimum_valid": True,
    }


def _is_ahead(direction: str, entry: float, level: Any) -> bool:
    if level is None:
        return False
    level = float(level)
    return level > entry if direction in {"LONG", "BUY"} else level < entry


def _quality_rank(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(value, 0)


def _policy(config: TargetPolicy | Any | None) -> TargetPolicy:
    if config is None:
        return TargetPolicy()
    return TargetPolicy(
        min_normal_reaction_target_pips=float(getattr(config, "min_normal_reaction_target_pips", 50.0)),
        preferred_reaction_target_pips=float(getattr(config, "preferred_reaction_target_pips", 100.0)),
        allow_vwap_1r_target=bool(getattr(config, "allow_vwap_1r_target", True)),
        min_vwap_target_pips=float(getattr(config, "min_vwap_target_pips", 30.0)),
        min_rr_normal=float(getattr(config, "min_rr_normal", 1.5)),
        min_rr_vwap_scalp=float(getattr(config, "min_rr_vwap_scalp", 1.0)),
    )


__all__ = ["TargetPolicy", "build_intelligent_targets", "validate_target_space"]
