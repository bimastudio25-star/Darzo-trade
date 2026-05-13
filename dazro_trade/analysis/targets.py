from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from dazro_trade.core.symbols import normalize_price, pips_to_price, price_to_pips


@dataclass(frozen=True)
class TargetPolicy:
    min_normal_reaction_target_pips: float = 50.0
    preferred_reaction_target_pips: float = 100.0

    allow_vwap_1r_target: bool = True
    min_vwap_target_pips: float = 30.0

    min_rr_normal: float = 1.5
    min_rr_vwap_scalp: float = 1.0

    max_official_targets: int = 3
    allow_runner_target: bool = True

    min_gap_between_official_targets_pips: float = 50.0
    min_gap_between_scalp_targets_pips: float = 30.0
    target_cluster_tolerance_pips: float = 25.0

    min_tp1_distance_pips: float = 50.0
    min_tp1_distance_pips_vwap_scalp: float = 30.0

    hide_micro_targets: bool = True
    max_candidate_targets_debug: int = 20

    show_theoretical_plan_on_watch: bool = True
    max_theoretical_targets_on_watch: int = 3


@dataclass
class TargetCandidate:
    price: float
    source: str
    basis: str
    distance_pips: float
    rr: float
    quality: str
    priority: int
    confluences: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TargetCluster:
    low: float
    high: float
    midpoint: float
    members: list[TargetCandidate]
    best_candidate: TargetCandidate
    distance_pips: float
    rr: float
    quality: str
    confluences: list[str] = field(default_factory=list)


LOGICAL_SOURCES = {
    "VWAP",
    "VWAP_BAND",
    "INTERNAL_LIQUIDITY",
    "EXTERNAL_LIQUIDITY",
    "EQUAL_HIGH",
    "EQUAL_LOW",
    "SESSION_HIGH",
    "SESSION_LOW",
    "PREVIOUS_DAY_HIGH",
    "PREVIOUS_DAY_LOW",
    "DAILY_MIDPOINT",
    "POC",
    "HVN",
    "LVN",
    "VOLUME_CRACK",
}
LIQUIDITY_SOURCES = {
    "INTERNAL_LIQUIDITY",
    "EXTERNAL_LIQUIDITY",
    "EQUAL_HIGH",
    "EQUAL_LOW",
    "SESSION_HIGH",
    "SESSION_LOW",
    "PREVIOUS_DAY_HIGH",
    "PREVIOUS_DAY_LOW",
}


def build_target_candidates(
    *,
    symbol: str,
    direction: str,
    entry: float,
    stop: float,
    vwap_snapshot: dict | None = None,
    liquidity_pools: list[dict] | None = None,
    volume_profile: dict | None = None,
    max_r: int = 10,
) -> list[TargetCandidate]:
    risk = abs(float(entry) - float(stop))
    if risk <= 0:
        return []

    candidates: list[TargetCandidate] = []
    if vwap_snapshot:
        vwap = vwap_snapshot.get("vwap")
        if _is_ahead(direction, entry, vwap):
            candidates.append(_candidate(symbol, direction, entry, risk, float(vwap), "VWAP", "VWAP", "high", 1, ["vwap_mean_reversion"]))
        for key in ("upper_1", "upper_2", "upper_3", "lower_1", "lower_2", "lower_3"):
            level = vwap_snapshot.get(key)
            if _is_ahead(direction, entry, level):
                candidates.append(_candidate(symbol, direction, entry, risk, float(level), "VWAP_BAND", f"VWAP band {key}", "medium", 1, [key]))

    for pool in liquidity_pools or []:
        level = pool.get("level")
        if not _is_ahead(direction, entry, level):
            continue
        source, basis, priority, quality = _liquidity_source(pool.get("pool_type", "liquidity"), pool.get("side"))
        confluences = [str(pool.get("pool_type", "liquidity"))]
        confluences.extend(str(item) for item in (pool.get("confluences") or []))
        candidates.append(
            _candidate(
                symbol,
                direction,
                entry,
                risk,
                float(level),
                source,
                basis,
                quality,
                priority,
                confluences,
                {"timeframe": pool.get("timeframe"), "pool_id": pool.get("id") or pool.get("pool_id")},
            )
        )

    if volume_profile:
        for key, source in (("poc", "POC"),):
            level = volume_profile.get(key)
            if _is_ahead(direction, entry, level):
                candidates.append(_candidate(symbol, direction, entry, risk, float(level), source, "volume node POC", "medium", 5, ["volume_profile"]))
        for key, source in (("hvn", "HVN"), ("lvn", "LVN")):
            for level in volume_profile.get(key) or []:
                if _is_ahead(direction, entry, level):
                    candidates.append(_candidate(symbol, direction, entry, risk, float(level), source, f"volume node {source}", "medium", 5, ["volume_profile"]))
        for low, high in volume_profile.get("volume_cracks") or []:
            boundary = low if _normal_direction(direction) == "SHORT" else high
            if _is_ahead(direction, entry, boundary):
                candidates.append(_candidate(symbol, direction, entry, risk, float(boundary), "VOLUME_CRACK", "volume crack boundary", "medium", 5, ["volume_crack"]))

    sign = 1 if _normal_direction(direction) == "LONG" else -1
    for multiple in range(1, max_r + 1):
        price = entry + sign * risk * multiple
        candidates.append(
            _candidate(
                symbol,
                direction,
                entry,
                risk,
                price,
                "R_MULTIPLE",
                f"{multiple}R mathematical",
                "medium" if multiple <= 3 else "low",
                6,
                [f"{multiple}R"],
                {"r_multiple": multiple},
            )
        )

    return _dedupe_candidates(symbol, candidates)


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
    candidates = build_target_candidates(
        symbol=symbol,
        direction=direction,
        entry=entry,
        stop=stop,
        vwap_snapshot=vwap_snapshot,
        liquidity_pools=liquidity_pools,
        volume_profile=volume_profile,
        max_r=max_r,
    )
    ladder = build_official_tp_ladder(
        symbol=symbol,
        direction=direction,
        entry=entry,
        stop=stop,
        candidates=candidates,
        policy=TargetPolicy(),
        setup_target_type="AUTO",
    )
    return ladder["official_targets"]


def cluster_target_candidates(
    candidates: list[TargetCandidate],
    symbol: str,
    tolerance_pips: float,
) -> list[TargetCluster]:
    if not candidates:
        return []
    tolerance = pips_to_price(symbol, tolerance_pips)
    ordered = sorted(candidates, key=lambda item: item.price)
    groups: list[list[TargetCandidate]] = []
    current: list[TargetCandidate] = []
    high = ordered[0].price
    for candidate in ordered:
        if not current or candidate.price - high <= tolerance:
            current.append(candidate)
            high = max(high, candidate.price)
        else:
            groups.append(current)
            current = [candidate]
            high = candidate.price
    if current:
        groups.append(current)

    clusters: list[TargetCluster] = []
    for group in groups:
        low = normalize_price(symbol, min(item.price for item in group))
        high = normalize_price(symbol, max(item.price for item in group))
        midpoint = normalize_price(symbol, sum(item.price for item in group) / len(group))
        best = _best_candidate(group)
        clusters.append(
            TargetCluster(
                low=low,
                high=high,
                midpoint=midpoint,
                members=list(group),
                best_candidate=best,
                distance_pips=best.distance_pips,
                rr=best.rr,
                quality=_best_quality(group),
                confluences=_merge_confluences(group),
            )
        )
    return clusters


def build_official_tp_ladder(
    *,
    symbol: str,
    direction: str,
    entry: float,
    stop: float,
    candidates: list[TargetCandidate] | list[dict],
    policy: TargetPolicy,
    setup_target_type: str,
) -> dict:
    policy = _policy(policy)
    risk_pips = price_to_pips(symbol, abs(float(entry) - float(stop)))
    reason_codes: list[str] = []
    candidate_objs = _coerce_candidates(candidates, symbol=symbol, direction=direction, entry=entry, stop=stop)
    candidate_objs = [candidate for candidate in candidate_objs if candidate.distance_pips > 0 and _is_ahead(direction, entry, candidate.price)]
    candidate_objs = sorted(candidate_objs, key=lambda item: (item.distance_pips, item.priority, -_quality_rank(item.quality)))
    candidate_debug = [_candidate_to_dict(item) for item in candidate_objs[: policy.max_candidate_targets_debug]]

    if risk_pips <= 0:
        return {
            "official_targets": [],
            "theoretical_targets": [],
            "candidate_targets": candidate_debug,
            "target_clusters": [],
            "runner_target": None,
            "validation": _validation(False, "NO_CLEAN_TARGET", 0, 0, None, ["invalid_risk"]),
            "reason_codes": ["invalid_risk"],
        }

    clusters = cluster_target_candidates(candidate_objs, symbol, policy.target_cluster_tolerance_pips)
    if any(len(cluster.members) > 1 for cluster in clusters):
        reason_codes.append("target_cluster_used")
    if any(len(cluster.members) > 1 and any(member.source in LIQUIDITY_SOURCES for member in cluster.members) for cluster in clusters):
        reason_codes.append("targets_clustered_nearby_liquidity")

    cluster_targets = [_cluster_target_dict(symbol, direction, entry, risk_pips, cluster) for cluster in clusters]
    cluster_targets = sorted(cluster_targets, key=lambda item: (item["distance_pips"], item["priority"]))

    scalp = _is_vwap_scalp(setup_target_type)
    if not scalp and policy.allow_vwap_1r_target and cluster_targets:
        first_vwap = next((item for item in cluster_targets if item["source"] in {"VWAP", "VWAP_BAND"}), None)
        if first_vwap and first_vwap["distance_pips"] >= policy.min_vwap_target_pips and first_vwap["rr"] >= policy.min_rr_vwap_scalp:
            scalp = setup_target_type in {"AUTO", "VWAP_1R_SCALP"} or setup_target_type.startswith("VWAP_1R_SCALP")

    min_tp1 = policy.min_tp1_distance_pips_vwap_scalp if scalp else policy.min_tp1_distance_pips
    gap_pips = policy.min_gap_between_scalp_targets_pips if scalp else policy.min_gap_between_official_targets_pips
    displayable: list[dict] = []
    for item in cluster_targets:
        if policy.hide_micro_targets and item["distance_pips"] < min_tp1:
            reason_codes.extend(["micro_target_hidden", "target_too_close_for_official_tp", "candidate_target_debug_only"])
            continue
        displayable.append(item)

    logical = [item for item in displayable if not item["pure_r_multiple"]]
    pure_r = [item for item in displayable if item["pure_r_multiple"]]
    selected: list[dict] = []
    for pool in (logical, pure_r):
        for item in pool:
            if selected and abs(item["price"] - selected[-1]["price"]) < pips_to_price(symbol, gap_pips):
                reason_codes.append("target_too_close_for_official_tp")
                continue
            selected.append(item)

    selected_official_targets = [_official_target(item, idx + 1) for idx, item in enumerate(selected[: policy.max_official_targets])]
    runner_target = None
    if policy.allow_runner_target and len(selected) > policy.max_official_targets:
        runner_target = _official_target(selected[policy.max_official_targets], policy.max_official_targets + 1, runner=True)
    theoretical_source = selected or displayable or cluster_targets
    theoretical_targets = [_official_target(item, idx + 1, theoretical=True) for idx, item in enumerate(theoretical_source[: policy.max_theoretical_targets_on_watch])]

    validation = _validate_ladder(
        official_targets=selected_official_targets,
        risk_pips=risk_pips,
        policy=policy,
        setup_target_type=setup_target_type,
        scalp=scalp,
        reason_codes=reason_codes,
    )
    if validation["valid"]:
        reason_codes.append("official_tp_ladder_valid")
        if any(item.get("cluster_range") for item in selected_official_targets):
            reason_codes.append("target_cluster_used")
    else:
        if not selected_official_targets:
            reason_codes.extend(["no_official_target_available", "no_clean_target_space_no_trade"])
        elif validation["target_pips"] < min_tp1:
            reason_codes.append("official_tp1_too_close")
        else:
            reason_codes.append("target_rr_insufficient")
    reason_codes = _dedupe_strings([*reason_codes, *validation["reason_codes"]])
    validation["reason_codes"] = _dedupe_strings(validation["reason_codes"])
    official_targets = selected_official_targets if validation["valid"] else []
    runner_target = runner_target if validation["valid"] else None

    return {
        "official_targets": official_targets,
        "theoretical_targets": theoretical_targets,
        "candidate_targets": candidate_debug,
        "target_clusters": [_cluster_to_dict(cluster) for cluster in clusters],
        "runner_target": runner_target,
        "validation": validation,
        "reason_codes": reason_codes,
    }


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
    if targets:
        candidates: list[TargetCandidate] | list[dict] = targets
    else:
        candidates = build_target_candidates(symbol=symbol, direction=direction, entry=entry, stop=stop, vwap_snapshot=vwap_snapshot, liquidity_pools=liquidity_pools or [])
    ladder = build_official_tp_ladder(
        symbol=symbol,
        direction=direction,
        entry=entry,
        stop=stop,
        candidates=candidates,
        policy=policy,
        setup_target_type="AUTO",
    )
    return ladder["validation"]


def _validate_ladder(
    *,
    official_targets: list[dict],
    risk_pips: float,
    policy: TargetPolicy,
    setup_target_type: str,
    scalp: bool,
    reason_codes: list[str],
) -> dict:
    if not official_targets:
        reasons = ["no_official_target_available", "no_clean_target_space_no_trade"]
        if any(reason == "target_too_close_for_official_tp" for reason in reason_codes):
            reasons.insert(0, "official_tp1_too_close")
        return _validation(False, "NO_CLEAN_TARGET", 0, 0, None, reasons)

    tp1 = official_targets[0]
    target_pips = float(tp1.get("distance_pips", 0) or 0)
    rr = float(tp1.get("rr", 0) or 0)
    if scalp and tp1.get("source") in {"VWAP", "VWAP_BAND"}:
        if target_pips < policy.min_tp1_distance_pips_vwap_scalp:
            return _validation(False, "NO_CLEAN_TARGET", target_pips, rr, tp1.get("price"), ["official_tp1_too_close"])
        if rr < policy.min_rr_vwap_scalp:
            return _validation(False, "NO_CLEAN_TARGET", target_pips, rr, tp1.get("price"), ["rr_below_minimum_vwap_scalp"])
        return _validation(True, "VWAP_1R_SCALP", target_pips, rr, tp1.get("price"), ["vwap_1r_target_valid", "official_tp1_valid"])

    if target_pips < policy.min_tp1_distance_pips:
        return _validation(False, "NO_CLEAN_TARGET", target_pips, rr, tp1.get("price"), ["official_tp1_too_close"])
    if rr < policy.min_rr_normal:
        return _validation(False, "NO_CLEAN_TARGET", target_pips, rr, tp1.get("price"), ["rr_below_minimum_normal"])

    reasons = ["official_tp1_valid", "normal_reaction_target_50_100_pips_valid"]
    if any(float(target.get("distance_pips", 0) or 0) >= policy.preferred_reaction_target_pips for target in official_targets):
        reasons.append("preferred_reaction_target_100_pips_available")
    return _validation(True, "NORMAL_REACTION", target_pips, rr, tp1.get("price"), reasons)


def _validation(valid: bool, setup_target_type: str, target_pips: float, rr: float, target_price: Any, reason_codes: list[str]) -> dict:
    return {
        "valid": valid,
        "setup_target_type": setup_target_type,
        "target_pips": round(float(target_pips), 1),
        "rr": round(float(rr), 2),
        "target_price": target_price,
        "reason_codes": _dedupe_strings(reason_codes),
    }


def _candidate(
    symbol: str,
    direction: str,
    entry: float,
    risk: float,
    price: float,
    source: str,
    basis: str,
    quality: str,
    priority: int,
    confluences: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> TargetCandidate:
    distance = abs(float(price) - float(entry))
    return TargetCandidate(
        price=normalize_price(symbol, price),
        source=source,
        basis=basis,
        distance_pips=round(price_to_pips(symbol, distance), 1),
        rr=round(distance / risk, 2) if risk else 0.0,
        quality=quality,
        priority=priority,
        confluences=confluences or [],
        metadata=metadata or {},
    )


def _cluster_target_dict(symbol: str, direction: str, entry: float, risk_pips: float, cluster: TargetCluster) -> dict:
    distance_pips = round(price_to_pips(symbol, abs(cluster.midpoint - entry)), 1)
    rr = round(distance_pips / risk_pips, 2) if risk_pips else 0.0
    best = _best_candidate(cluster.members)
    sources = {member.source for member in cluster.members}
    basis = _cluster_basis(cluster)
    return {
        "price": cluster.midpoint,
        "distance_pips": distance_pips,
        "rr": rr,
        "basis": basis,
        "cluster_range": [cluster.low, cluster.high] if len(cluster.members) > 1 else None,
        "quality": cluster.quality,
        "source": best.source,
        "priority": min(member.priority for member in cluster.members),
        "confluences": cluster.confluences,
        "pure_r_multiple": sources == {"R_MULTIPLE"},
        "metadata": {
            "member_count": len(cluster.members),
            "sources": sorted(sources),
            "direction": _normal_direction(direction),
        },
    }


def _official_target(item: dict, index: int, *, runner: bool = False, theoretical: bool = False) -> dict:
    out = {
        "label": "RUNNER" if runner else f"TP{index}",
        "price": item["price"],
        "distance_pips": item["distance_pips"],
        "rr": item["rr"],
        "basis": item["basis"],
        "cluster_range": item.get("cluster_range"),
        "quality": item["quality"],
        "confluences": list(item.get("confluences") or []),
        "source": item.get("source"),
        "metadata": dict(item.get("metadata") or {}),
    }
    if theoretical:
        out["theoretical"] = True
    return out


def _cluster_basis(cluster: TargetCluster) -> str:
    sources = {member.source for member in cluster.members}
    if len(cluster.members) > 1:
        if sources & LIQUIDITY_SOURCES:
            return "liquidity cluster"
        if sources & {"VWAP", "VWAP_BAND"}:
            return "VWAP cluster"
        if sources & {"POC", "HVN", "LVN", "VOLUME_CRACK"}:
            return "volume cluster"
    return cluster.best_candidate.basis


def _liquidity_source(pool_type: Any, side: Any = None) -> tuple[str, str, int, str]:
    kind = str(pool_type or "").lower()
    side_text = str(side or "").lower()
    if "equal_high" in kind:
        return "EQUAL_HIGH", "equal highs liquidity", 2, "high"
    if "equal_low" in kind:
        return "EQUAL_LOW", "equal lows liquidity", 2, "high"
    if "session_high" in kind:
        return "SESSION_HIGH", "session high liquidity", 3, "high"
    if "session_low" in kind:
        return "SESSION_LOW", "session low liquidity", 3, "high"
    if "previous_day_high" in kind or kind == "pdh":
        return "PREVIOUS_DAY_HIGH", "previous day high liquidity", 4, "high"
    if "previous_day_low" in kind or kind == "pdl":
        return "PREVIOUS_DAY_LOW", "previous day low liquidity", 4, "high"
    if "external" in kind or "daily_range" in kind:
        return "EXTERNAL_LIQUIDITY", "external liquidity", 2, "high"
    if "internal" in kind or side_text in {"buy_side", "sell_side"}:
        return "INTERNAL_LIQUIDITY", "internal liquidity", 2, "medium"
    return "INTERNAL_LIQUIDITY", "liquidity pool", 2, "medium"


def _coerce_candidates(
    candidates: list[TargetCandidate] | list[dict],
    *,
    symbol: str,
    direction: str,
    entry: float,
    stop: float,
) -> list[TargetCandidate]:
    risk = abs(float(entry) - float(stop))
    out: list[TargetCandidate] = []
    for item in candidates:
        if isinstance(item, TargetCandidate):
            out.append(item)
            continue
        price = item.get("price")
        if price is None:
            continue
        source = str(item.get("source") or _source_from_basis(item.get("basis"), item.get("label")))
        basis = str(item.get("basis") or item.get("label") or source)
        out.append(
            _candidate(
                symbol,
                direction,
                entry,
                risk,
                float(price),
                source,
                basis,
                str(item.get("quality") or "medium"),
                int(item.get("priority") or _priority_for_source(source)),
                list(item.get("confluences") or []),
                dict(item.get("metadata") or {}),
            )
        )
    return _dedupe_candidates(symbol, out)


def _source_from_basis(basis: Any, label: Any = None) -> str:
    text = f"{basis or ''} {label or ''}".lower()
    if "vwap" in text:
        return "VWAP_BAND" if "band" in text or "upper" in text or "lower" in text else "VWAP"
    if "equal high" in text:
        return "EQUAL_HIGH"
    if "equal low" in text:
        return "EQUAL_LOW"
    if "previous day high" in text:
        return "PREVIOUS_DAY_HIGH"
    if "previous day low" in text:
        return "PREVIOUS_DAY_LOW"
    if "session high" in text:
        return "SESSION_HIGH"
    if "session low" in text:
        return "SESSION_LOW"
    if "liquidity" in text:
        return "EXTERNAL_LIQUIDITY" if "external" in text else "INTERNAL_LIQUIDITY"
    if "poc" in text:
        return "POC"
    if "hvn" in text:
        return "HVN"
    if "lvn" in text:
        return "LVN"
    if "volume" in text:
        return "VOLUME_CRACK"
    if "r" in text:
        return "R_MULTIPLE"
    return "R_MULTIPLE"


def _priority_for_source(source: str) -> int:
    return {
        "VWAP": 1,
        "VWAP_BAND": 1,
        "INTERNAL_LIQUIDITY": 2,
        "EXTERNAL_LIQUIDITY": 2,
        "EQUAL_HIGH": 2,
        "EQUAL_LOW": 2,
        "SESSION_HIGH": 3,
        "SESSION_LOW": 3,
        "PREVIOUS_DAY_HIGH": 4,
        "PREVIOUS_DAY_LOW": 4,
        "POC": 5,
        "HVN": 5,
        "LVN": 5,
        "VOLUME_CRACK": 5,
        "R_MULTIPLE": 6,
        "EMA50": 7,
        "EMA200": 7,
    }.get(source, 6)


def _dedupe_candidates(symbol: str, candidates: list[TargetCandidate]) -> list[TargetCandidate]:
    dedup: dict[float, TargetCandidate] = {}
    for item in candidates:
        key = normalize_price(symbol, item.price)
        old = dedup.get(key)
        if old is None or (item.priority, -_quality_rank(item.quality), item.distance_pips) < (old.priority, -_quality_rank(old.quality), old.distance_pips):
            dedup[key] = item
    return sorted(dedup.values(), key=lambda item: (item.distance_pips, item.priority))


def _candidate_to_dict(candidate: TargetCandidate) -> dict:
    return asdict(candidate)


def _cluster_to_dict(cluster: TargetCluster) -> dict:
    return {
        "low": cluster.low,
        "high": cluster.high,
        "midpoint": cluster.midpoint,
        "members": [_candidate_to_dict(member) for member in cluster.members],
        "best_candidate": _candidate_to_dict(cluster.best_candidate),
        "distance_pips": cluster.distance_pips,
        "rr": cluster.rr,
        "quality": cluster.quality,
        "confluences": list(cluster.confluences),
    }


def _best_candidate(candidates: list[TargetCandidate]) -> TargetCandidate:
    return sorted(candidates, key=lambda item: (item.priority, -_quality_rank(item.quality), item.distance_pips))[0]


def _best_quality(candidates: list[TargetCandidate]) -> str:
    return sorted((item.quality for item in candidates), key=_quality_rank, reverse=True)[0]


def _merge_confluences(candidates: list[TargetCandidate]) -> list[str]:
    values: list[str] = []
    for candidate in candidates:
        values.append(candidate.source.lower())
        values.extend(str(item) for item in candidate.confluences)
    return _dedupe_strings(values)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _is_ahead(direction: str, entry: float, level: Any) -> bool:
    if level is None:
        return False
    level = float(level)
    return level > entry if _normal_direction(direction) == "LONG" else level < entry


def _normal_direction(direction: str) -> str:
    return "LONG" if str(direction).upper() in {"LONG", "BUY"} else "SHORT"


def _is_vwap_scalp(setup_target_type: str) -> bool:
    return str(setup_target_type or "").upper().startswith("VWAP_1R_SCALP")


def _quality_rank(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(str(value).lower(), 0)


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
        max_official_targets=int(getattr(config, "max_official_targets", 3)),
        allow_runner_target=bool(getattr(config, "allow_runner_target", True)),
        min_gap_between_official_targets_pips=float(getattr(config, "min_gap_between_official_targets_pips", 50.0)),
        min_gap_between_scalp_targets_pips=float(getattr(config, "min_gap_between_scalp_targets_pips", 30.0)),
        target_cluster_tolerance_pips=float(getattr(config, "target_cluster_tolerance_pips", 25.0)),
        min_tp1_distance_pips=float(getattr(config, "min_tp1_distance_pips", 50.0)),
        min_tp1_distance_pips_vwap_scalp=float(getattr(config, "min_tp1_distance_pips_vwap_scalp", 30.0)),
        hide_micro_targets=bool(getattr(config, "hide_micro_targets", True)),
        max_candidate_targets_debug=int(getattr(config, "max_candidate_targets_debug", 20)),
        show_theoretical_plan_on_watch=bool(getattr(config, "show_theoretical_plan_on_watch", True)),
        max_theoretical_targets_on_watch=int(getattr(config, "max_theoretical_targets_on_watch", 3)),
    )


__all__ = [
    "TargetCandidate",
    "TargetCluster",
    "TargetPolicy",
    "build_intelligent_targets",
    "build_official_tp_ladder",
    "build_target_candidates",
    "cluster_target_candidates",
    "validate_target_space",
]
