from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Literal

import pandas as pd

from dazro_trade.analysis.targets import TargetPolicy, build_intelligent_targets, validate_target_space
from dazro_trade.analysis.volume_profile import build_volume_profile
from dazro_trade.analysis.vwap import vwap_snapshot
from dazro_trade.core.models import ScalpingDecision, SetupState, SetupZone, ZoneRole
from dazro_trade.core.symbols import price_to_pips, pips_to_price
from dazro_trade.liquidity.map import LiquidityPool, build_liquidity_map, important_reaction_pools
from dazro_trade.liquidity.sweep import SweepEvent, detect_sweeps_for_pools

DirectionWord = Literal["BUY", "SELL"]
TradeDirection = Literal["LONG", "SHORT", "WAIT"]

LTF_TIMEFRAMES = {"M15", "M5", "M1"}
HTF_TIMEFRAMES = {"H1", "H4", "D1"}


@dataclass(frozen=True)
class ScalpingConfig:
    max_m1_distance_points: float = 2.5
    max_m5_distance_points: float = 5.0
    max_m15_distance_points: float = 8.0
    max_htf_context_distance_points: float = 50.0
    max_m1_distance_pips: float = 250.0
    max_m5_distance_pips: float = 500.0
    max_m15_distance_pips: float = 800.0
    min_reaction_distance_pips: float = 80.0
    min_signal_score: int = 85
    min_rr: float = 2.0
    entry_buffer_points: float = 0.30
    invalidation_buffer_points: float = 0.80
    strict_closed_candle: bool = True
    min_normal_reaction_target_pips: float = 50.0
    preferred_reaction_target_pips: float = 100.0
    allow_vwap_1r_target: bool = True
    min_vwap_target_pips: float = 30.0
    min_rr_normal: float = 1.5
    min_rr_vwap_scalp: float = 1.0


@dataclass
class InteractionResult:
    zone_touched: bool = False
    entry_area_touched: bool = False
    first_touch_time: datetime | None = None
    last_touch_time: datetime | None = None
    touch_price: float | None = None
    source_timeframe: str | None = None
    missed_touch_detected: bool = False
    reaction_after_touch: str | None = None
    reaction_points: float = 0.0


@dataclass
class SignalDeduplicator:
    sent_keys: set[str] = field(default_factory=set)

    def signal_key(self, decision: ScalpingDecision, session_name: str = "unknown", trade_date: date | None = None) -> str:
        zone = decision.primary_zone
        day = (trade_date or decision.timestamp_utc.date()).isoformat()
        if zone is None:
            return f"{decision.symbol}:{decision.direction}:no-zone:{session_name}:{day}"
        return ":".join(
            [
                decision.symbol,
                decision.direction,
                zone.timeframe,
                zone.zone_type,
                str(round(zone.low, 1)),
                str(round(zone.high, 1)),
                session_name,
                day,
            ]
        )

    def is_duplicate(self, decision: ScalpingDecision, session_name: str = "unknown", trade_date: date | None = None) -> bool:
        return self.signal_key(decision, session_name=session_name, trade_date=trade_date) in self.sent_keys

    def mark_sent(self, decision: ScalpingDecision, session_name: str = "unknown", trade_date: date | None = None) -> str:
        key = self.signal_key(decision, session_name=session_name, trade_date=trade_date)
        self.sent_keys.add(key)
        return key


def evaluate_scalping_setup(
    market_data: dict[str, pd.DataFrame],
    *,
    symbol: str = "XAUUSD",
    current_price: float | None = None,
    spread: float = 0.0,
    max_spread: float = 30.0,
    now_utc: datetime | None = None,
    last_scan_time: datetime | None = None,
    session_name: str = "unknown",
    config: ScalpingConfig | None = None,
) -> ScalpingDecision:
    cfg = config or ScalpingConfig()
    now = now_utc or datetime.now(timezone.utc)
    frames = {tf: normalize_frame(df) for tf, df in market_data.items() if df is not None}
    price = float(current_price if current_price is not None else _infer_price(frames))

    missing = [tf for tf in ("M1", "M5", "M15") if _frame_empty(frames.get(tf))]
    htf_context = build_htf_context(frames, price)
    volume_profile = build_volume_profile(frames.get("M15", pd.DataFrame()))
    vwap = vwap_snapshot(frames.get("M15", pd.DataFrame()), price)
    liquidity_pools = build_liquidity_map(frames, symbol=symbol, current_price=price)
    live_sweep_events = detect_sweeps_for_pools(
        important_reaction_pools(liquidity_pools, min_pips=0, max_pips=500),
        frames.get("M1", frames.get("M5", pd.DataFrame())),
        m5_df=frames.get("M5"),
        m1_df=frames.get("M1"),
        vwap_df=frames.get("M15"),
        volume_profile=volume_profile,
        current_candle_closed=False,
    )
    closed_sweep_events = detect_sweeps_for_pools(
        important_reaction_pools(liquidity_pools, min_pips=0, max_pips=500),
        _closed_frame(frames.get("M1", frames.get("M5", pd.DataFrame()))),
        m5_df=_closed_frame(frames.get("M5")),
        m1_df=_closed_frame(frames.get("M1")),
        vwap_df=frames.get("M15"),
        volume_profile=volume_profile,
        current_candle_closed=True,
    )
    sweep_events = _merge_sweep_events(live_sweep_events, closed_sweep_events)
    zones = build_zones(frames, symbol=symbol, current_price=price, config=cfg)
    liquidity = build_liquidity_context(frames, price, pools=liquidity_pools, sweeps=sweep_events, vwap=vwap, volume_profile=volume_profile)
    intraday_context = build_intraday_context(frames, price)
    if missing:
        return ScalpingDecision(
            symbol=symbol,
            setup_type="NO_TRADE",
            direction="WAIT",
            state="WATCH",
            score=0,
            confidence=0.0,
            htf_context=htf_context,
            intraday_context={**intraday_context, "session": session_name},
            liquidity=liquidity,
            reason_codes=["missing_ltf_data"],
            rejection_reasons=[f"Dati {', '.join(missing)} non disponibili, impossibile generare segnale scalping"],
            events=[],
            timestamp_utc=now,
        )

    primary = choose_primary_zone(zones, price, cfg)
    top_sweep = sweep_events[0] if sweep_events else None
    if top_sweep is not None and top_sweep.status == "accepted_breakout":
        return _decision_from_sweep(
            top_sweep,
            symbol=symbol,
            price=price,
            htf_context=htf_context,
            intraday_context={**intraday_context, "session": session_name},
            liquidity=liquidity,
            now=now,
            config=cfg,
            forced_state="WATCH",
            rejection_reasons=["accepted_breakout_not_reversal"],
        )
    if primary is None and top_sweep is not None:
        if top_sweep.status == "TRIGGERED":
            return _decision_from_sweep(
                top_sweep,
                symbol=symbol,
                price=price,
                htf_context=htf_context,
                intraday_context={**intraday_context, "session": session_name, "confirmations_present": top_sweep.reason_codes, "confirmations_missing": []},
                liquidity=liquidity,
                now=now,
                config=cfg,
                forced_state="TRIGGERED",
                rejection_reasons=[],
            )
        if top_sweep.status in {"ARMED", "SWEEPING_INTRABAR", "CONFIRMED_SWEEP"}:
            reason = {
                "ARMED": "remote_liquidity_found_but_not_armed",
                "SWEEPING_INTRABAR": "sweep_intrabar_waiting_closed_candle",
                "CONFIRMED_SWEEP": "sweep_confirmed_missing_m1_choch",
            }.get(top_sweep.status, "liquidity_reaction_watch")
            return _decision_from_sweep(
                top_sweep,
                symbol=symbol,
                price=price,
                htf_context=htf_context,
                intraday_context={**intraday_context, "session": session_name},
                liquidity=liquidity,
                now=now,
                config=cfg,
                forced_state="ARMED",
                rejection_reasons=[reason, *top_sweep.reason_codes],
            )
    if primary is None:
        remote_count = len([z for z in zones if z.role == "HTF_CONTEXT" and (z.distance_from_price or 0) > cfg.max_m15_distance_points])
        return ScalpingDecision(
            symbol=symbol,
            setup_type="NO_TRADE",
            direction="WAIT",
            state="WATCH",
            score=0,
            confidence=0.0,
            htf_context={**htf_context, "remote_zones": remote_count},
            intraday_context={**intraday_context, "session": session_name},
            liquidity=liquidity,
            reason_codes=["no_near_ltf_zone"],
            rejection_reasons=["Nessuna zona M15/M5/M1 operativa vicina al prezzo"],
            events=_zone_events(zones, price),
            timestamp_utc=now,
        )

    direction: TradeDirection = "LONG" if primary.direction == "BUY" else "SHORT"
    interactions = detect_zone_interactions_since_last_scan(
        primary,
        frames.get("M1"),
        frames.get("M5"),
        last_scan_time=last_scan_time,
        now_utc=now,
    )
    apply_interactions(primary, interactions)

    sweep = detect_sweep_direction(_closed_frame(frames["M15"]))
    m5_displacement = detect_displacement(_closed_frame(frames["M5"]), primary.direction)
    m5_structure = detect_structure_confirmation(_closed_frame(frames["M5"]), primary.direction)
    m1_trigger = detect_micro_trigger(_closed_frame(frames["M1"]), primary.direction)
    fvg_after_sweep = primary.zone_type in {"bullish_fvg", "bearish_fvg", "bullish_ifvg", "bearish_ifvg"} and bool(sweep_events)
    htf_alignment = htf_allows_direction(htf_context, primary.direction)
    rr_payload = build_risk_targets(
        primary,
        direction,
        cfg,
        symbol=symbol,
        vwap_data=vwap.__dict__ if vwap is not None else None,
        liquidity_pools=[pool.__dict__ for pool in liquidity_pools],
        volume_profile=volume_profile.__dict__,
    )

    confirmations_present: list[str] = []
    confirmations_missing: list[str] = []
    if htf_alignment:
        confirmations_present.append("HTF non contrario")
    else:
        confirmations_missing.append("HTF contrario o neutro debole")
    if sweep == primary.direction:
        confirmations_present.append("sweep liquidity M15 coerente")
    else:
        confirmations_missing.append("sweep M15 assente")
    if m5_displacement:
        confirmations_present.append("displacement M5 confermato su candela chiusa")
    else:
        confirmations_missing.append("displacement M5 assente")
    if m5_structure:
        confirmations_present.append("BOS/CHoCH M5 coerente")
    else:
        confirmations_missing.append("BOS/CHoCH M5 assente")
    if m1_trigger:
        confirmations_present.append("trigger M1 presente")
    else:
        confirmations_missing.append("trigger M1 assente")
    if spread <= max_spread:
        confirmations_present.append("spread ok")
    else:
        confirmations_missing.append("spread alto")
    if rr_payload["rr"] >= cfg.min_rr:
        confirmations_present.append("RR valido")
    else:
        confirmations_missing.append("RR insufficiente")

    score = score_setup(
        htf_alignment=htf_alignment,
        sweep=sweep == primary.direction,
        displacement=m5_displacement,
        m5_structure=m5_structure,
        m1_trigger=m1_trigger,
        fvg_after_sweep=fvg_after_sweep,
        spread_ok=spread <= max_spread,
        rr_ok=rr_payload["rr"] >= cfg.min_rr,
        entry_already_touched=interactions.entry_area_touched,
        distance=price_to_pips(symbol, primary.distance_from_price or 0.0),
    )

    state = classify_setup_state(
        score=score,
        all_hard_filters=all(
            [
                htf_alignment,
                sweep == primary.direction,
                m5_displacement,
                m5_structure,
                m1_trigger,
                spread <= max_spread,
                rr_payload["rr"] >= cfg.min_rr,
            ]
        ),
        entry_area_touched=interactions.entry_area_touched,
    )
    primary.state = state
    primary.score = score
    primary.metadata.update(
        {
            "classification": "LTF operative zone",
            "confirmations_present": confirmations_present,
            "confirmations_missing": confirmations_missing,
            "session": session_name,
            "touch": interactions.__dict__,
            "sweep_events": [event.__dict__ for event in sweep_events[:3]],
        }
    )

    rejection_reasons = list(confirmations_missing)
    if interactions.entry_area_touched:
        rejection_reasons.insert(0, "Entry area gia toccata, non inseguire")
    if primary.role == "HTF_CONTEXT":
        rejection_reasons.insert(0, "Zona HTF usata come contesto, non entry scalping")
    if primary.zone_type in {"bullish_fvg", "bearish_fvg"} and not sweep_events:
        rejection_reasons.append("fvg_without_liquidity_penalty")
    if not rr_payload["target_validation"]["valid"]:
        rejection_reasons.extend(rr_payload["target_validation"]["reason_codes"])
    if score < cfg.min_signal_score:
        rejection_reasons.append(f"score {score}/{cfg.min_signal_score}")

    setup_type = classify_setup_type(htf_context, primary.direction, sweep == primary.direction)
    decision = ScalpingDecision(
        symbol=symbol,
        setup_type=setup_type if state == "TRIGGERED" else ("WATCH" if state == "WATCH" else "ARMED"),
        direction=direction,
        state=state,
        score=score,
        confidence=round(score / 100, 2),
        htf_context=htf_context,
        intraday_context={
            **intraday_context,
            "session": session_name,
            "confirmations_present": confirmations_present,
            "confirmations_missing": confirmations_missing,
            "spread": spread,
        },
        liquidity={**liquidity, "m15_sweep": sweep},
        primary_zone=primary,
        entry_area=rr_payload["entry_area"],
        stop=rr_payload["stop"],
        targets=rr_payload["targets"],
        invalidation=rr_payload["stop"],
        reason_codes=confirmations_present,
        rejection_reasons=rejection_reasons,
        events=_zone_events([primary], price),
        timestamp_utc=now,
    )
    _apply_execution_gates(decision, price)
    if decision.is_operational_signal:
        decision.signal_id = SignalDeduplicator().signal_key(decision, session_name=session_name, trade_date=now.date())
    return decision


def build_zones(
    frames: dict[str, pd.DataFrame],
    *,
    symbol: str,
    current_price: float,
    config: ScalpingConfig | None = None,
) -> list[SetupZone]:
    cfg = config or ScalpingConfig()
    zones: list[SetupZone] = []
    for timeframe in ("H4", "H1", "M15", "M5", "M1"):
        df = _closed_frame(frames.get(timeframe))
        if _frame_empty(df):
            continue
        role = zone_role_for_timeframe(timeframe)
        for zone_type, low, high, direction, reason in _detect_fvg_zones(df):
            zone = SetupZone(
                id=make_zone_id(symbol, timeframe, zone_type, low, high),
                symbol=symbol,
                timeframe=timeframe,
                zone_type=zone_type,
                role=role,
                state="WATCH",
                direction=direction,
                low=round(low, 2),
                high=round(high, 2),
                reason_codes=[reason],
            )
            enrich_zone_distance(zone, current_price, cfg)
            zones.append(zone)
        for zone_type, low, high, direction, reason in _detect_order_blocks(df):
            zone = SetupZone(
                id=make_zone_id(symbol, timeframe, zone_type, low, high),
                symbol=symbol,
                timeframe=timeframe,
                zone_type=zone_type,
                role=role,
                state="WATCH",
                direction=direction,
                low=round(low, 2),
                high=round(high, 2),
                reason_codes=[reason],
            )
            enrich_zone_distance(zone, current_price, cfg)
            zones.append(zone)
    return sorted(zones, key=lambda z: (zone_sort_bucket(z), z.distance_from_price if z.distance_from_price is not None else 9999))


def choose_primary_zone(zones: Iterable[SetupZone], current_price: float, config: ScalpingConfig | None = None) -> SetupZone | None:
    cfg = config or ScalpingConfig()
    operative = []
    for zone in zones:
        distance = zone_distance(zone, current_price)
        zone.distance_from_price = distance
        distance_pips = price_to_pips(zone.symbol, distance)
        zone.metadata["distance_pips"] = round(distance_pips, 1)
        if zone.timeframe == "M15" and distance_pips <= cfg.max_m15_distance_pips:
            operative.append(zone)
        elif zone.timeframe == "M5" and distance_pips <= cfg.max_m5_distance_pips:
            operative.append(zone)
        elif zone.timeframe == "M1" and distance_pips <= cfg.max_m1_distance_pips:
            operative.append(zone)
    if not operative:
        return None
    return sorted(operative, key=lambda z: (zone_sort_bucket(z), z.distance_from_price or 0.0))[0]


def detect_zone_interactions_since_last_scan(
    zone: SetupZone,
    candles_m1: pd.DataFrame | None,
    candles_m5: pd.DataFrame | None,
    ticks: pd.DataFrame | None = None,
    *,
    last_scan_time: datetime | None,
    now_utc: datetime | None,
) -> InteractionResult:
    now = now_utc or datetime.now(timezone.utc)
    for source_name, frame in (("tick", ticks), ("M1", candles_m1), ("M5", candles_m5)):
        interaction = _detect_interaction_from_frame(zone, frame, source_name, last_scan_time, now)
        if interaction.zone_touched or interaction.entry_area_touched:
            return interaction
    return InteractionResult()


def apply_interactions(zone: SetupZone, interactions: InteractionResult) -> None:
    if interactions.zone_touched:
        zone.touched = True
        zone.metadata["has_been_touched"] = True
        zone.metadata["first_touch_time"] = interactions.first_touch_time.isoformat() if interactions.first_touch_time else None
        zone.metadata["last_touch_time"] = interactions.last_touch_time.isoformat() if interactions.last_touch_time else None
        zone.metadata["touch_price"] = interactions.touch_price
        zone.metadata["touch_source_timeframe"] = interactions.source_timeframe
        zone.metadata["missed_touch_detected"] = interactions.missed_touch_detected
        zone.metadata["reaction_after_touch"] = interactions.reaction_after_touch
        zone.metadata["reaction_points"] = interactions.reaction_points
    if interactions.entry_area_touched:
        zone.entry_area_touched = True
        zone.metadata["entry_area_touched"] = True
        zone.metadata["entry_area_touched_at"] = interactions.last_touch_time.isoformat() if interactions.last_touch_time else None


def score_setup(
    *,
    htf_alignment: bool,
    sweep: bool,
    displacement: bool,
    m5_structure: bool,
    m1_trigger: bool,
    fvg_after_sweep: bool,
    spread_ok: bool,
    rr_ok: bool,
    entry_already_touched: bool,
    distance: float,
) -> int:
    score = 0
    score += 15 if htf_alignment else 0
    score += 20 if sweep else 0
    score += 15 if displacement else 0
    score += 15 if m5_structure else 0
    score += 20 if m1_trigger else 0
    score += 10 if fvg_after_sweep else 0
    score += 5 if spread_ok else -15
    score += 10 if rr_ok else -20
    if distance > 800:
        score -= 30
    if entry_already_touched:
        score -= 50
    return max(0, min(100, score))


def classify_setup_state(*, score: int, all_hard_filters: bool, entry_area_touched: bool) -> SetupState:
    if entry_area_touched:
        return "ENTERED"
    if all_hard_filters and score >= 85:
        return "TRIGGERED"
    if score >= 70:
        return "ARMED"
    return "WATCH"


def _apply_execution_gates(decision: ScalpingDecision, current_price: float) -> None:
    if decision.direction == "SHORT":
        if decision.stop is not None and current_price >= decision.stop:
            decision.state = "INVALIDATED"
            decision.rejection_reasons.insert(0, "current_price_above_short_stop")
            decision.reason_codes.append("setup_invalidated_before_signal")
            if decision.primary_zone:
                decision.primary_zone.state = "INVALIDATED"
            return
        if decision.entry_area and current_price < decision.entry_area[0] and not (decision.primary_zone and decision.primary_zone.entry_area_touched):
            decision.state = "ENTERED"
            decision.rejection_reasons.insert(0, "entry_missed_do_not_chase")
            decision.reason_codes.append("setup_already_played")
            if decision.primary_zone:
                decision.primary_zone.state = "ENTERED"
            return
    if decision.direction == "LONG":
        if decision.stop is not None and current_price <= decision.stop:
            decision.state = "INVALIDATED"
            decision.rejection_reasons.insert(0, "current_price_below_long_stop")
            decision.reason_codes.append("setup_invalidated_before_signal")
            if decision.primary_zone:
                decision.primary_zone.state = "INVALIDATED"
            return
        if decision.entry_area and current_price > decision.entry_area[1] and not (decision.primary_zone and decision.primary_zone.entry_area_touched):
            decision.state = "ENTERED"
            decision.rejection_reasons.insert(0, "entry_missed_do_not_chase")
            decision.reason_codes.append("setup_already_played")
            if decision.primary_zone:
                decision.primary_zone.state = "ENTERED"


def apply_execution_gates(decision: ScalpingDecision, current_price: float) -> ScalpingDecision:
    _apply_execution_gates(decision, current_price)
    return decision


def classify_setup_type(htf_context: dict[str, Any], direction: DirectionWord | None, sweep_ok: bool) -> str:
    if direction is None:
        return "NO_TRADE"
    desired = "bullish" if direction == "BUY" else "bearish"
    h1 = htf_context.get("h1_bias")
    h4 = htf_context.get("h4_bias")
    if h1 == desired or h4 == desired:
        return "TREND_FOLLOWING_LONG" if direction == "BUY" else "TREND_FOLLOWING_SHORT"
    if sweep_ok:
        return "REVERSAL_LONG" if direction == "BUY" else "REVERSAL_SHORT"
    return "NO_TRADE"


def build_risk_targets(
    zone: SetupZone,
    direction: TradeDirection,
    config: ScalpingConfig | None = None,
    *,
    symbol: str = "XAUUSD",
    vwap_data: dict | None = None,
    liquidity_pools: list[dict] | None = None,
    volume_profile: dict | None = None,
) -> dict[str, Any]:
    cfg = config or ScalpingConfig()
    entry_low = round(max(zone.low, zone.midpoint - cfg.entry_buffer_points), 2)
    entry_high = round(min(zone.high, zone.midpoint + cfg.entry_buffer_points), 2)
    entry = round((entry_low + entry_high) / 2, 2)
    if direction == "LONG":
        stop = round(zone.low - cfg.invalidation_buffer_points, 2)
        risk = max(entry - stop, 0.01)
    elif direction == "SHORT":
        stop = round(zone.high + cfg.invalidation_buffer_points, 2)
        risk = max(stop - entry, 0.01)
    else:
        stop = None
        risk = 0.0
    if stop is None:
        targets = []
        validation = {"valid": False, "setup_target_type": "NO_CLEAN_TARGET", "target_pips": 0, "rr": 0, "target_price": None, "reason_codes": ["invalid_risk"]}
    else:
        targets = build_intelligent_targets(
            symbol=symbol,
            direction=direction,
            entry=entry,
            stop=stop,
            vwap_snapshot=vwap_data,
            liquidity_pools=liquidity_pools or [],
            volume_profile=volume_profile,
        )
        validation = validate_target_space(symbol, direction, entry, stop, targets, vwap_data, liquidity_pools or [], _target_policy(cfg))
    return {"entry_area": (entry_low, entry_high), "entry": entry, "stop": stop, "targets": targets, "rr": validation.get("rr", 0), "target_validation": validation}


def _dynamic_r_targets(entry: float, risk: float, direction: TradeDirection) -> list[dict[str, Any]]:
    targets = []
    for multiple in range(1, 11):
        price = entry + risk * multiple if direction == "LONG" else entry - risk * multiple
        if multiple == 1:
            basis = "1R primo take profit / gestione rischio"
        elif multiple == 2:
            basis = "2R liquidity interna"
        elif multiple == 3:
            basis = "3R continuation target"
        elif multiple <= 5:
            basis = "runner solo se momentum e spazio reale"
        else:
            basis = "extended runner 6R-10R solo senza ostacoli HTF"
        targets.append({"label": f"TP{multiple}", "price": round(price, 2), "basis": basis, "r_multiple": multiple})
    return targets


def _target_policy(config: ScalpingConfig) -> TargetPolicy:
    return TargetPolicy(
        min_normal_reaction_target_pips=config.min_normal_reaction_target_pips,
        preferred_reaction_target_pips=config.preferred_reaction_target_pips,
        allow_vwap_1r_target=config.allow_vwap_1r_target,
        min_vwap_target_pips=config.min_vwap_target_pips,
        min_rr_normal=config.min_rr_normal,
        min_rr_vwap_scalp=config.min_rr_vwap_scalp,
    )


def build_htf_context(frames: dict[str, pd.DataFrame], price: float) -> dict[str, Any]:
    h1 = _closed_frame(frames.get("H1"))
    h4 = _closed_frame(frames.get("H4"))
    return {
        "h1_bias": infer_bias(h1),
        "h4_bias": infer_bias(h4),
        "premium_discount": infer_premium_discount(h1 if not _frame_empty(h1) else h4, price),
        "quarterly_block": "not_configured",
        "role": "H4/H1 context only; M15/M5/M1 required for scalping signal",
    }


def build_intraday_context(frames: dict[str, pd.DataFrame], price: float) -> dict[str, Any]:
    m15 = _closed_frame(frames.get("M15"))
    m5 = _closed_frame(frames.get("M5"))
    m1 = _closed_frame(frames.get("M1"))
    return {
        "m15_bias": infer_bias(m15),
        "m5_bias": infer_bias(m5),
        "m1_bias": infer_bias(m1),
        "m15_sweep": detect_sweep_direction(m15),
        "m5_buy_displacement": detect_displacement(m5, "BUY"),
        "m5_sell_displacement": detect_displacement(m5, "SELL"),
        "m1_buy_trigger": detect_micro_trigger(m1, "BUY"),
        "m1_sell_trigger": detect_micro_trigger(m1, "SELL"),
        "current_price": price,
    }


def build_liquidity_context(
    frames: dict[str, pd.DataFrame],
    price: float,
    *,
    pools: list[LiquidityPool] | None = None,
    sweeps: list[SweepEvent] | None = None,
    vwap: Any | None = None,
    volume_profile: Any | None = None,
) -> dict[str, Any]:
    m15 = _closed_frame(frames.get("M15"))
    liquidity_pools = pools or []
    sweep_events = sweeps or []
    if _frame_empty(m15):
        return {
            "external": "unknown",
            "internal": "unknown",
            "price": price,
            "pools": [pool.__dict__ | {"distance_band": pool.distance_band} for pool in liquidity_pools[:20]],
            "sweeps": [event.__dict__ for event in sweep_events[:10]],
        }
    high = float(m15["h"].tail(50).max())
    low = float(m15["l"].tail(50).min())
    return {
        "external_high": round(high, 2),
        "external_low": round(low, 2),
        "price_vs_range": "premium" if price > (high + low) / 2 else "discount",
        "price": price,
        "pools": [pool.__dict__ | {"distance_band": pool.distance_band} for pool in liquidity_pools[:20]],
        "reaction_pools": [pool.__dict__ | {"distance_band": pool.distance_band} for pool in important_reaction_pools(liquidity_pools)[:10]],
        "sweeps": [event.__dict__ for event in sweep_events[:10]],
        "vwap": vwap.__dict__ if vwap is not None else None,
        "volume_profile": volume_profile.__dict__ if volume_profile is not None else None,
    }


def infer_bias(df: pd.DataFrame | None) -> str:
    if _frame_empty(df) or len(df) < 10:
        return "neutral"
    close = df["c"].astype(float)
    fast = float(close.tail(5).mean())
    slow = float(close.tail(10).mean())
    if fast > slow:
        return "bullish"
    if fast < slow:
        return "bearish"
    return "neutral"


def infer_premium_discount(df: pd.DataFrame | None, price: float) -> str:
    if _frame_empty(df) or len(df) < 5:
        return "unknown"
    high = float(df["h"].tail(50).max())
    low = float(df["l"].tail(50).min())
    mid = (high + low) / 2
    if price > mid:
        return "premium"
    if price < mid:
        return "discount"
    return "equilibrium"


def htf_allows_direction(htf_context: dict[str, Any], direction: DirectionWord | None) -> bool:
    if direction is None:
        return False
    desired = "bullish" if direction == "BUY" else "bearish"
    opposite = "bearish" if desired == "bullish" else "bullish"
    biases = [htf_context.get("h1_bias"), htf_context.get("h4_bias")]
    if desired in biases:
        return True
    return opposite not in biases


def detect_sweep_direction(df: pd.DataFrame | None, lookback: int = 20) -> DirectionWord | None:
    if _frame_empty(df) or len(df) < lookback + 1:
        return None
    prev = df.iloc[-lookback - 1 : -1]
    last = df.iloc[-1]
    prev_high = float(prev["h"].max())
    prev_low = float(prev["l"].min())
    if float(last["h"]) > prev_high and float(last["c"]) < prev_high:
        return "SELL"
    if float(last["l"]) < prev_low and float(last["c"]) > prev_low:
        return "BUY"
    return None


def detect_displacement(df: pd.DataFrame | None, direction: DirectionWord | None) -> bool:
    if direction is None or _frame_empty(df) or len(df) < 8:
        return False
    bodies = (df["c"].astype(float) - df["o"].astype(float)).abs()
    avg_body = float(bodies.iloc[-8:-1].mean() or 0)
    last = df.iloc[-1]
    body = abs(float(last["c"]) - float(last["o"]))
    bullish = float(last["c"]) > float(last["o"])
    bearish = float(last["c"]) < float(last["o"])
    return body >= max(avg_body * 1.2, 0.01) and ((direction == "BUY" and bullish) or (direction == "SELL" and bearish))


def detect_structure_confirmation(df: pd.DataFrame | None, direction: DirectionWord | None, lookback: int = 10) -> bool:
    if direction is None or _frame_empty(df) or len(df) < lookback + 1:
        return False
    prev = df.iloc[-lookback - 1 : -1]
    last_close = float(df["c"].iloc[-1])
    if direction == "BUY":
        return last_close > float(prev["h"].max())
    return last_close < float(prev["l"].min())


def detect_micro_trigger(df: pd.DataFrame | None, direction: DirectionWord | None) -> bool:
    if direction is None or _frame_empty(df) or len(df) < 4:
        return False
    prev = df.iloc[-2]
    last = df.iloc[-1]
    if direction == "BUY":
        return float(last["c"]) > float(last["o"]) and float(last["c"]) > float(prev["h"])
    return float(last["c"]) < float(last["o"]) and float(last["c"]) < float(prev["l"])


def zone_role_for_timeframe(timeframe: str) -> ZoneRole:
    if timeframe in HTF_TIMEFRAMES:
        return "HTF_CONTEXT"
    if timeframe == "M1":
        return "ENTRY_TRIGGER"
    return "LTF_SETUP"


def enrich_zone_distance(zone: SetupZone, current_price: float, config: ScalpingConfig) -> None:
    zone.distance_from_price = zone_distance(zone, current_price)
    distance_pips = price_to_pips(zone.symbol, zone.distance_from_price)
    zone.metadata["distance_pips"] = round(distance_pips, 1)
    if zone.role == "HTF_CONTEXT":
        zone.metadata["classification"] = "HTF_CONTEXT" if zone.distance_from_price <= config.max_htf_context_distance_points else "REMOTE_HTF_CONTEXT"
    elif distance_pips <= config.max_m15_distance_pips:
        zone.metadata["classification"] = "OPERATIVE_ZONE"
    else:
        zone.metadata["classification"] = "REMOTE_ZONE"


def zone_distance(zone: SetupZone, current_price: float) -> float:
    if current_price < zone.low:
        return round(zone.low - current_price, 2)
    if current_price > zone.high:
        return round(current_price - zone.high, 2)
    return 0.0


def zone_sort_bucket(zone: SetupZone) -> tuple[int, int]:
    timeframe_rank = {"M15": 0, "M5": 1, "M1": 2, "H1": 3, "H4": 4, "D1": 5}.get(zone.timeframe, 9)
    role_rank = {"LTF_SETUP": 0, "ENTRY_TRIGGER": 1, "HTF_CONTEXT": 2, "TARGET": 3}.get(zone.role, 9)
    return role_rank, timeframe_rank


def make_zone_id(symbol: str, timeframe: str, zone_type: str, low: float, high: float) -> str:
    return f"{symbol}_{timeframe}_{zone_type}_{round(low, 2)}_{round(high, 2)}".replace(".", "_")


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    out = df.copy()
    rename = {"open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol"}
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], utc=True)
    return out


def _closed_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    if _frame_empty(df):
        return pd.DataFrame()
    if len(df) > 3:
        return df.iloc[:-1].copy()
    return df.copy()


def _frame_empty(df: pd.DataFrame | None) -> bool:
    return df is None or len(df) == 0 or not {"o", "h", "l", "c"}.issubset(df.columns)


def _infer_price(frames: dict[str, pd.DataFrame]) -> float:
    for tf in ("M1", "M5", "M15", "H1", "H4"):
        df = frames.get(tf)
        if not _frame_empty(df):
            return float(df["c"].iloc[-1])
    return 0.0


def _detect_fvg_zones(df: pd.DataFrame) -> list[tuple[str, float, float, DirectionWord, str]]:
    zones: list[tuple[str, float, float, DirectionWord, str]] = []
    if _frame_empty(df) or len(df) < 3:
        return zones
    for i in range(2, len(df)):
        low = float(df["l"].iloc[i])
        high_two_back = float(df["h"].iloc[i - 2])
        high = float(df["h"].iloc[i])
        low_two_back = float(df["l"].iloc[i - 2])
        if low > high_two_back:
            zones.append(("bullish_fvg", high_two_back, low, "BUY", "FVG bullish dopo displacement"))
        if high < low_two_back:
            zones.append(("bearish_fvg", high, low_two_back, "SELL", "FVG bearish dopo displacement"))
    return zones[-4:]


def _detect_order_blocks(df: pd.DataFrame) -> list[tuple[str, float, float, DirectionWord, str]]:
    zones: list[tuple[str, float, float, DirectionWord, str]] = []
    if _frame_empty(df) or len(df) < 5:
        return zones
    for i in range(3, len(df)):
        curr = df.iloc[i]
        prev = df.iloc[i - 1]
        body = abs(float(curr["c"]) - float(curr["o"]))
        rng = max(float(curr["h"]) - float(curr["l"]), 0.01)
        strong = body / rng >= 0.55
        if not strong:
            continue
        if float(curr["c"]) > float(curr["o"]) and float(prev["c"]) < float(prev["o"]):
            zones.append(("bullish_ob", float(prev["l"]), float(prev["h"]), "BUY", "last down candle before bullish displacement"))
        if float(curr["c"]) < float(curr["o"]) and float(prev["c"]) > float(prev["o"]):
            zones.append(("bearish_ob", float(prev["l"]), float(prev["h"]), "SELL", "last up candle before bearish displacement"))
    return zones[-3:]


def _detect_interaction_from_frame(
    zone: SetupZone,
    frame: pd.DataFrame | None,
    source_name: str,
    last_scan_time: datetime | None,
    now_utc: datetime,
) -> InteractionResult:
    if frame is None or len(frame) == 0:
        return InteractionResult()
    df = normalize_frame(frame)
    if "time" in df.columns:
        if last_scan_time is not None:
            df = df[(df["time"] >= pd.Timestamp(last_scan_time)) & (df["time"] <= pd.Timestamp(now_utc))]
        else:
            df = df.tail(12)
    if len(df) == 0:
        return InteractionResult()
    low_col = "bid" if source_name == "tick" and "bid" in df.columns and zone.direction == "SELL" else "l"
    high_col = "ask" if source_name == "tick" and "ask" in df.columns and zone.direction == "BUY" else "h"
    if low_col not in df.columns or high_col not in df.columns:
        low_col, high_col = "l", "h"
    touched = df[(df[low_col].astype(float) <= zone.high) & (df[high_col].astype(float) >= zone.low)]
    if touched.empty:
        return InteractionResult()
    first = touched.iloc[0]
    last = touched.iloc[-1]
    first_time = _row_time(first)
    last_time = _row_time(last)
    touch_price = float(first[low_col]) if zone.direction == "BUY" else float(first[high_col])
    after = df[df["time"] >= last_time].head(4) if "time" in df.columns and last_time else df.tail(4)
    reaction = _reaction_after_touch(zone, after, touch_price)
    return InteractionResult(
        zone_touched=True,
        entry_area_touched=True,
        first_touch_time=first_time,
        last_touch_time=last_time,
        touch_price=round(touch_price, 2),
        source_timeframe=source_name,
        missed_touch_detected=True,
        reaction_after_touch=reaction[0],
        reaction_points=reaction[1],
    )


def _reaction_after_touch(zone: SetupZone, after: pd.DataFrame, touch_price: float) -> tuple[str | None, float]:
    if len(after) == 0:
        return None, 0.0
    if zone.direction == "BUY":
        move = float(after["h"].astype(float).max()) - touch_price
        return ("bullish" if move > 0 else None, round(max(move, 0.0), 2))
    move = touch_price - float(after["l"].astype(float).min())
    return ("bearish" if move > 0 else None, round(max(move, 0.0), 2))


def _row_time(row: pd.Series) -> datetime | None:
    if "time" not in row:
        return None
    ts = pd.Timestamp(row["time"]).to_pydatetime()
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _zone_events(zones: Iterable[SetupZone], price: float) -> list[dict[str, Any]]:
    events = []
    for zone in zones:
        event_type = "ZONE_TOUCHED" if zone.touched else "ZONE_WATCH"
        if zone.entry_area_touched:
            event_type = "ENTRY_AREA_TOUCHED"
        events.append(
            {
                "type": event_type,
                "zone_id": zone.id,
                "timeframe": zone.timeframe,
                "zone_type": zone.zone_type,
                "state": zone.state,
                "distance": zone_distance(zone, price),
            }
        )
    return events


def _merge_sweep_events(live: list[SweepEvent], closed: list[SweepEvent]) -> list[SweepEvent]:
    by_pool: dict[str, SweepEvent] = {}
    rank = {"TRIGGERED": 6, "CONFIRMED_SWEEP": 5, "SWEEPING_INTRABAR": 4, "ARMED": 3, "accepted_breakout": 2, "WATCH": 1}
    for event in [*live, *closed]:
        old = by_pool.get(event.pool_id)
        if old is None or rank.get(event.status, 0) > rank.get(old.status, 0) or event.score > old.score:
            by_pool[event.pool_id] = event
    return sorted(by_pool.values(), key=lambda item: (-rank.get(item.status, 0), -item.score, item.penetration_pips))


def _decision_from_sweep(
    sweep: SweepEvent,
    *,
    symbol: str,
    price: float,
    htf_context: dict[str, Any],
    intraday_context: dict[str, Any],
    liquidity: dict[str, Any],
    now: datetime,
    config: ScalpingConfig,
    forced_state: SetupState,
    rejection_reasons: list[str],
) -> ScalpingDecision:
    direction: DirectionWord = "SELL" if sweep.direction == "bearish_reversal_candidate" else "BUY"
    trade_direction: TradeDirection = "SHORT" if direction == "SELL" else "LONG"
    zone_low = sweep.level - pips_to_price(symbol, 25)
    zone_high = sweep.level + pips_to_price(symbol, 25)
    zone = SetupZone(
        id=f"{symbol}_sweep_{round(sweep.level, 2)}".replace(".", "_"),
        symbol=symbol,
        timeframe=sweep.timeframe,
        zone_type="buy_side_liquidity_sweep" if direction == "SELL" else "sell_side_liquidity_sweep",
        role="LTF_SETUP",
        state=forced_state,
        direction=direction,
        low=round(zone_low, 2),
        high=round(zone_high, 2),
        reason_codes=list(sweep.reason_codes),
        score=max(sweep.score, config.min_signal_score if forced_state == "TRIGGERED" else sweep.score),
        distance_from_price=round(abs(price - sweep.level), 2),
        metadata={
            "sweep_status": sweep.status,
            "penetration_pips": sweep.penetration_pips,
            "liquidity_level": sweep.level,
        },
    )
    rr_payload = build_risk_targets(zone, trade_direction, config, symbol=symbol, vwap_data=liquidity.get("vwap"), liquidity_pools=liquidity.get("pools", []), volume_profile=liquidity.get("volume_profile"))
    setup_type = "REVERSAL_SHORT" if trade_direction == "SHORT" else "REVERSAL_LONG"
    if sweep.accepted_breakout:
        setup_type = "TREND_FOLLOWING_SHORT" if trade_direction == "SHORT" else "TREND_FOLLOWING_LONG"
    decision = ScalpingDecision(
        symbol=symbol,
        setup_type=setup_type if forced_state == "TRIGGERED" else "LIQUIDITY_REACTION",
        direction=trade_direction,
        state=forced_state,
        score=zone.score,
        confidence=round(zone.score / 100, 2),
        htf_context=htf_context,
        intraday_context={
            **intraday_context,
            "confirmations_present": list(sweep.reason_codes) if forced_state == "TRIGGERED" else [],
            "confirmations_missing": rejection_reasons if forced_state != "TRIGGERED" else [],
        },
        liquidity=liquidity,
        primary_zone=zone,
        entry_area=rr_payload["entry_area"],
        stop=rr_payload["stop"],
        targets=rr_payload["targets"],
        invalidation=rr_payload["stop"],
        reason_codes=list(sweep.reason_codes),
        rejection_reasons=rejection_reasons,
        events=[
            {
                "type": "LIQUIDITY_SWEEP",
                "status": sweep.status,
                "level": sweep.level,
                "direction": sweep.direction,
                "score": sweep.score,
                "reason_codes": sweep.reason_codes,
            }
        ],
        timestamp_utc=now,
    )
    if not rr_payload["target_validation"]["valid"] and forced_state == "TRIGGERED":
        decision.state = "ARMED"
        decision.rejection_reasons.extend(rr_payload["target_validation"]["reason_codes"])
    _apply_execution_gates(decision, price)
    return decision


__all__ = [
    "InteractionResult",
    "ScalpingConfig",
    "SignalDeduplicator",
    "apply_interactions",
    "build_zones",
    "choose_primary_zone",
    "detect_zone_interactions_since_last_scan",
    "evaluate_scalping_setup",
    "apply_execution_gates",
    "score_setup",
]
