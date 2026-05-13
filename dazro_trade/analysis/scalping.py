from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Literal

import pandas as pd

from dazro_trade.analysis.indicators import multi_tf_ema_context, multi_tf_rsi_context
from dazro_trade.analysis.session_candles import classify_session_candle
from dazro_trade.analysis.targets import TargetPolicy, build_official_tp_ladder, build_target_candidates
from dazro_trade.analysis.time_behaviour import classify_time_behaviour
from dazro_trade.analysis.volume_profile import build_daily_anchored_profile, build_volume_profile, daily_range_from
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
    max_m1_distance_pips: float = 25.0
    max_m5_distance_pips: float = 50.0
    max_m15_distance_pips: float = 80.0
    min_reaction_distance_pips: float = 8.0
    min_signal_score: int = 85
    min_rr: float = 2.0
    entry_buffer_points: float = 0.30
    invalidation_buffer_points: float = 0.80
    strict_closed_candle: bool = True
    min_normal_reaction_target_pips: float = 5.0
    preferred_reaction_target_pips: float = 10.0
    allow_vwap_1r_target: bool = True
    min_vwap_target_pips: float = 3.0
    min_rr_normal: float = 1.5
    min_rr_vwap_scalp: float = 1.0
    max_official_targets: int = 3
    allow_runner_target: bool = True
    min_gap_between_official_targets_pips: float = 5.0
    min_gap_between_scalp_targets_pips: float = 3.0
    target_cluster_tolerance_pips: float = 2.5
    min_tp1_distance_pips: float = 5.0
    min_tp1_distance_pips_vwap_scalp: float = 3.0
    hide_micro_targets: bool = True
    max_candidate_targets_debug: int = 20
    show_theoretical_plan_on_watch: bool = True
    max_theoretical_targets_on_watch: int = 3
    theoretical_sl_buffer_pips: float = 1.0
    min_stop_distance_pips: float = 2.0
    max_stop_distance_pips: float = 15.0


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


@dataclass(frozen=True)
class PrimaryConfluenceResult:
    passed: bool
    reasons_present: list[str]
    reasons_missing: list[str]
    score_bonus: int


def evaluate_primary_confluence(
    sweep: SweepEvent | None,
    primary_zone: SetupZone | None,
    htf_allows: bool,
    m5_displacement_ok: bool,
    m1_trigger_ok: bool,
    *,
    max_zone_distance_pips: float = 8.0,
) -> PrimaryConfluenceResult:
    present: list[str] = []
    missing: list[str] = []
    if sweep is None or sweep.status not in {"CONFIRMED_SWEEP", "TRIGGERED"}:
        missing.append("sweep_not_in_confirmed_or_triggered")
    else:
        present.append("sweep_confirmed_or_triggered")
    if sweep is None or not sweep.number_theory_confluence:
        missing.append("number_theory_missing")
    else:
        present.append("number_theory_confluence")
    if sweep is None or not (sweep.fvg_after_sweep or sweep.ifvg_after_sweep):
        missing.append("fvg_or_ifvg_missing")
    else:
        present.append("fvg_or_ifvg_after_sweep")
    if primary_zone is None or primary_zone.distance_from_price is None:
        missing.append("primary_zone_missing")
    else:
        distance_pips = price_to_pips(primary_zone.symbol, primary_zone.distance_from_price)
        if distance_pips > max_zone_distance_pips:
            missing.append("primary_zone_too_far")
        else:
            present.append("primary_zone_near_sweep")
    if htf_allows:
        present.append("htf_allows_direction")
    else:
        missing.append("htf_blocks_direction")
    if m5_displacement_ok:
        present.append("m5_displacement")
    else:
        missing.append("m5_displacement_missing")
    if m1_trigger_ok:
        present.append("m1_trigger")
    else:
        missing.append("m1_trigger_missing")
    passed = not missing
    score_bonus = 0
    if passed and sweep is not None:
        score_bonus = 10
        if sweep.vwap_deviation_confluence:
            score_bonus += 5
        if sweep.volume_crack_confluence:
            score_bonus += 5
        score_bonus = min(20, score_bonus)
    return PrimaryConfluenceResult(passed=passed, reasons_present=present, reasons_missing=missing, score_bonus=score_bonus)


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
    max_spread: float = 3.0,
    now_utc: datetime | None = None,
    last_scan_time: datetime | None = None,
    session_name: str = "unknown",
    config: ScalpingConfig | None = None,
    timezone_name: str = "Europe/Rome",
    broker_time_offset_hours: int = 0,
) -> ScalpingDecision:
    cfg = config or ScalpingConfig()
    now = now_utc or datetime.now(timezone.utc)
    frames = {tf: normalize_frame(df) for tf, df in market_data.items() if df is not None}
    price = float(current_price if current_price is not None else _infer_price(frames))
    ema_contexts = multi_tf_ema_context(frames, price, symbol=symbol)
    rsi_contexts = multi_tf_rsi_context(frames)
    time_context = classify_time_behaviour(now, frames, timezone=timezone_name, broker_time_offset_hours=broker_time_offset_hours)

    missing = [tf for tf in ("M1", "M5", "M15") if _frame_empty(frames.get(tf))]
    htf_context = build_htf_context(frames, price, ema_contexts=ema_contexts, rsi_contexts=rsi_contexts)
    htf_context["time_behaviour"] = time_context.to_dict()
    intraday_for_vp = frames.get("M5") if not _frame_empty(frames.get("M5")) else frames.get("M15", pd.DataFrame())
    _dr = daily_range_from(frames.get("D1"), now_utc=now)
    if _dr is not None and not _frame_empty(intraday_for_vp):
        volume_profile = build_daily_anchored_profile(_dr[0], _dr[1], intraday_for_vp)
        volume_profile_source = f"daily_anchored:{_dr[2]}"
    else:
        volume_profile = build_volume_profile(intraday_for_vp)
        volume_profile_source = "intraday_fallback"
    vwap = vwap_snapshot(frames.get("M15", pd.DataFrame()), price)
    liquidity_pools = build_liquidity_map(frames, symbol=symbol, current_price=price)
    live_sweep_events = detect_sweeps_for_pools(
        important_reaction_pools(liquidity_pools, min_pips=0, max_pips=50),
        frames.get("M1", frames.get("M5", pd.DataFrame())),
        m5_df=frames.get("M5"),
        m1_df=frames.get("M1"),
        vwap_df=frames.get("M15"),
        volume_profile=volume_profile,
        current_candle_closed=False,
    )
    closed_sweep_events = detect_sweeps_for_pools(
        important_reaction_pools(liquidity_pools, min_pips=0, max_pips=50),
        _closed_frame(frames.get("M1", frames.get("M5", pd.DataFrame()))),
        m5_df=_closed_frame(frames.get("M5")),
        m1_df=_closed_frame(frames.get("M1")),
        vwap_df=frames.get("M15"),
        volume_profile=volume_profile,
        current_candle_closed=True,
    )
    sweep_events = _merge_sweep_events(live_sweep_events, closed_sweep_events)
    zones = build_zones(frames, symbol=symbol, current_price=price, config=cfg)
    liquidity = build_liquidity_context(frames, price, pools=liquidity_pools, sweeps=sweep_events, vwap=vwap, volume_profile=volume_profile, volume_profile_source=volume_profile_source)
    session_event = build_session_candle_context(
        symbol=symbol,
        frames=frames,
        session_name=session_name,
        time_context=time_context,
        ema_contexts=ema_contexts,
        vwap_data=vwap.__dict__ if vwap is not None else None,
        liquidity_pools=[event.__dict__ for event in sweep_events],
    )
    intraday_context = build_intraday_context(frames, price, ema_contexts=ema_contexts, rsi_contexts=rsi_contexts)
    intraday_context["time_behaviour"] = time_context.to_dict()
    intraday_context["session_candle"] = session_event
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
                forced_state=top_sweep.status,
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
    target_ok = target_validation_passes(rr_payload["target_validation"], cfg)
    target_type = rr_payload["target_validation"].get("setup_target_type")
    ema_filter = ema_trade_filter(ema_contexts, primary.direction, sweep == primary.direction, m5_structure, fvg_after_sweep)
    rsi_filter = rsi_trade_filter(rsi_contexts, primary.direction)

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
    if target_ok:
        confirmations_present.append("target/RR valido")
    else:
        confirmations_missing.append("target/RR insufficiente")
    confirmations_present.extend(ema_filter["present"])
    confirmations_present.extend(rsi_filter["present"])
    confirmations_missing.extend(ema_filter["missing"])
    confirmations_missing.extend(rsi_filter["missing"])
    time_filter = time_behaviour_filter(time_context.to_dict(), session_event, m5_displacement, m5_structure)
    confirmations_present.extend(time_filter["present"])
    confirmations_missing.extend(time_filter["missing"])

    score = score_setup(
        htf_alignment=htf_alignment,
        sweep=sweep == primary.direction,
        displacement=m5_displacement,
        m5_structure=m5_structure,
        m1_trigger=m1_trigger,
        fvg_after_sweep=fvg_after_sweep,
        spread_ok=spread <= max_spread,
        rr_ok=target_ok,
        entry_already_touched=interactions.entry_area_touched,
        distance=price_to_pips(symbol, primary.distance_from_price or 0.0),
    )
    if time_filter["score_penalty"]:
        score = max(0, score - time_filter["score_penalty"])
    top_sweep = sweep_events[0] if sweep_events else None
    confluence = evaluate_primary_confluence(top_sweep, primary, htf_alignment, m5_displacement, m1_trigger)
    score = min(100, score + confluence.score_bonus)

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
                target_ok,
                ema_filter["passes"],
                time_filter["passes"],
            ]
        ),
        entry_area_touched=interactions.entry_area_touched,
    )
    if confluence.passed:
        confirmations_present.append("primary_confluence_chain")
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
            "primary_confluence": {
                "passed": confluence.passed,
                "present": confluence.reasons_present,
                "missing": confluence.reasons_missing,
            },
        }
    )

    rejection_reasons = list(confirmations_missing)
    if interactions.entry_area_touched:
        rejection_reasons.insert(0, "Entry area gia toccata, non inseguire")
    if primary.role == "HTF_CONTEXT":
        rejection_reasons.insert(0, "Zona HTF usata come contesto, non entry scalping")
    if primary.zone_type in {"bullish_fvg", "bearish_fvg"} and not sweep_events:
        rejection_reasons.append("fvg_without_liquidity_penalty")
    if not target_ok:
        rejection_reasons.extend(rr_payload["target_validation"]["reason_codes"])
    if score < cfg.min_signal_score:
        rejection_reasons.append(f"score {score}/{cfg.min_signal_score}")
    if state == "TRIGGERED" and not confluence.passed:
        state = "ARMED"
        primary.state = state
        rejection_reasons.append("primary_confluence_incomplete")
        rejection_reasons.extend(confluence.reasons_missing)

    setup_type = classify_setup_type(htf_context, primary.direction, sweep == primary.direction)
    if state == "TRIGGERED":
        setup_type = _triggered_strategy_mode(top_sweep)
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
        entry=rr_payload["entry"],
        stop=rr_payload["stop"],
        targets=rr_payload["targets"] if state in {"TRIGGERED", "REENTRY_VALID"} else [],
        theoretical_targets=rr_payload["theoretical_targets"],
        target_candidates=rr_payload["target_candidates"],
        target_clusters=rr_payload["target_clusters"],
        target_validation=rr_payload["target_validation"],
        invalidation=rr_payload["stop"],
        reason_codes=confirmations_present,
        rejection_reasons=rejection_reasons,
        events=_zone_events([primary], price),
        timestamp_utc=now,
    )
    _apply_execution_gates(decision, price)
    _sync_non_operational_targets(decision)
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
            decision.score = 0
            decision.confidence = 0.0
            if decision.primary_zone:
                decision.primary_zone.state = "INVALIDATED"
            return
        if (
            decision.primary_zone
            and decision.primary_zone.high < current_price
            and decision.primary_zone.zone_type in {"bearish_ob", "bearish_fvg", "bearish_ifvg"}
        ):
            decision.state = "INVALIDATED"
            decision.rejection_reasons.insert(0, "short_zone_below_current_price_invalid")
            decision.reason_codes.append("setup_invalidated_before_signal")
            decision.score = 0
            decision.confidence = 0.0
            decision.primary_zone.state = "INVALIDATED"
            return
        if decision.entry_area and current_price < decision.entry_area[0] and not (decision.primary_zone and decision.primary_zone.entry_area_touched):
            _mark_entry_missed(decision)
            return
    if decision.direction == "LONG":
        if decision.stop is not None and current_price <= decision.stop:
            decision.state = "INVALIDATED"
            decision.rejection_reasons.insert(0, "current_price_below_long_stop")
            decision.reason_codes.append("setup_invalidated_before_signal")
            decision.score = 0
            decision.confidence = 0.0
            if decision.primary_zone:
                decision.primary_zone.state = "INVALIDATED"
            return
        if (
            decision.primary_zone
            and decision.primary_zone.low > current_price
            and decision.primary_zone.zone_type in {"bullish_ob", "bullish_fvg", "bullish_ifvg"}
        ):
            decision.state = "INVALIDATED"
            decision.rejection_reasons.insert(0, "long_zone_above_current_price_invalid")
            decision.reason_codes.append("setup_invalidated_before_signal")
            decision.score = 0
            decision.confidence = 0.0
            decision.primary_zone.state = "INVALIDATED"
            return
        if decision.entry_area and current_price > decision.entry_area[1] and not (decision.primary_zone and decision.primary_zone.entry_area_touched):
            _mark_entry_missed(decision)
            return
    if decision.state == "ENTERED" and decision.primary_zone and not decision.primary_zone.entry_area_touched and not decision.primary_zone.touched:
        decision.state = "EXPIRED"
        decision.primary_zone.state = "EXPIRED"
        decision.rejection_reasons.insert(0, "entered_state_requires_entry_touch")
        decision.reason_codes.extend(["entered_state_requires_entry_touch", "state_corrected_from_entered_to_not_actionable"])
        decision.score = min(decision.score, 70)
        decision.confidence = round(decision.score / 100, 2)


def _mark_entry_missed(decision: ScalpingDecision) -> None:
    decision.state = "EXPIRED"
    decision.rejection_reasons.insert(0, "entry_missed_do_not_chase")
    decision.reason_codes.extend(["entry_missed_do_not_chase", "state_corrected_from_entered_to_not_actionable"])
    decision.score = min(decision.score, 70)
    decision.confidence = round(decision.score / 100, 2)
    if decision.primary_zone:
        decision.primary_zone.state = "EXPIRED"


def _sync_non_operational_targets(decision: ScalpingDecision) -> None:
    if decision.state not in {"TRIGGERED", "REENTRY_VALID"}:
        decision.targets = []
        if "theoretical_plan_only" not in decision.reason_codes:
            decision.reason_codes.extend(
                [
                    "theoretical_plan_only",
                    "theoretical_sl_not_operational",
                    "theoretical_targets_not_operational",
                    "waiting_for_trigger_before_entry",
                ]
            )


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
        theoretical_targets = []
        target_candidates = []
        target_clusters = []
        validation = {"valid": False, "setup_target_type": "NO_CLEAN_TARGET", "target_pips": 0, "rr": 0, "target_price": None, "reason_codes": ["invalid_risk"]}
    else:
        candidates = build_target_candidates(
            symbol=symbol,
            direction=direction,
            entry=entry,
            stop=stop,
            vwap_snapshot=vwap_data,
            liquidity_pools=liquidity_pools or [],
            volume_profile=volume_profile,
        )
        setup_target_type = _setup_target_type_for_ladder(direction, vwap_data, entry)
        ladder = build_official_tp_ladder(
            symbol=symbol,
            direction=direction,
            entry=entry,
            stop=stop,
            candidates=candidates,
            policy=_target_policy(cfg),
            setup_target_type=setup_target_type,
        )
        targets = ladder["official_targets"]
        theoretical_targets = ladder["theoretical_targets"]
        target_candidates = ladder["candidate_targets"]
        target_clusters = ladder["target_clusters"]
        validation = ladder["validation"]
        validation["reason_codes"] = _dedupe_reason_codes([*validation.get("reason_codes", []), *_stop_validation_reasons(symbol, entry, stop, zone, cfg)])
        if any(reason in validation["reason_codes"] for reason in {"theoretical_sl_too_tight", "theoretical_sl_too_wide"}):
            validation["valid"] = False
            validation["setup_target_type"] = "NO_CLEAN_TARGET"
    return {
        "entry_area": (entry_low, entry_high),
        "entry": entry,
        "stop": stop,
        "targets": targets,
        "theoretical_targets": theoretical_targets,
        "target_candidates": target_candidates,
        "target_clusters": target_clusters,
        "target_validation": validation,
        "rr": validation.get("rr", 0),
    }


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
        max_official_targets=config.max_official_targets,
        allow_runner_target=config.allow_runner_target,
        min_gap_between_official_targets_pips=config.min_gap_between_official_targets_pips,
        min_gap_between_scalp_targets_pips=config.min_gap_between_scalp_targets_pips,
        target_cluster_tolerance_pips=config.target_cluster_tolerance_pips,
        min_tp1_distance_pips=config.min_tp1_distance_pips,
        min_tp1_distance_pips_vwap_scalp=config.min_tp1_distance_pips_vwap_scalp,
        hide_micro_targets=config.hide_micro_targets,
        max_candidate_targets_debug=config.max_candidate_targets_debug,
        show_theoretical_plan_on_watch=config.show_theoretical_plan_on_watch,
        max_theoretical_targets_on_watch=config.max_theoretical_targets_on_watch,
    )


def _setup_target_type_for_ladder(direction: TradeDirection, vwap_data: dict | None, entry: float) -> str:
    if not vwap_data:
        return "NORMAL_REACTION"
    vwap = vwap_data.get("vwap")
    if vwap is None:
        return "NORMAL_REACTION"
    if direction == "LONG" and float(vwap) > entry:
        return "VWAP_1R_SCALP_LONG"
    if direction == "SHORT" and float(vwap) < entry:
        return "VWAP_1R_SCALP_SHORT"
    return "NORMAL_REACTION"


def _stop_validation_reasons(symbol: str, entry: float, stop: float, zone: SetupZone, config: ScalpingConfig) -> list[str]:
    reasons: list[str] = []
    zone_type = zone.zone_type.lower()
    if "sweep" in zone_type or "liquidity" in zone_type:
        reasons.append("theoretical_sl_from_sweep_level")
    elif "fvg" in zone_type or "ifvg" in zone_type:
        reasons.append("theoretical_sl_from_fvg_boundary")
    else:
        reasons.append("theoretical_sl_from_swing")
    distance_pips = price_to_pips(symbol, abs(entry - stop))
    if distance_pips < config.min_stop_distance_pips:
        reasons.append("theoretical_sl_too_tight")
    elif distance_pips > config.max_stop_distance_pips:
        reasons.append("theoretical_sl_too_wide")
    else:
        reasons.append("theoretical_sl_distance_valid")
    return reasons


def _dedupe_reason_codes(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def target_validation_passes(validation: dict[str, Any], config: ScalpingConfig | None = None) -> bool:
    cfg = config or ScalpingConfig()
    if not validation.get("valid"):
        return False
    target_type = validation.get("setup_target_type")
    rr = float(validation.get("rr", 0) or 0)
    target_pips = float(validation.get("target_pips", 0) or 0)
    if target_type == "VWAP_1R_SCALP":
        return rr >= cfg.min_rr_vwap_scalp and target_pips >= cfg.min_vwap_target_pips
    if target_type == "NORMAL_REACTION":
        return rr >= cfg.min_rr_normal and target_pips >= cfg.min_normal_reaction_target_pips
    return False


def _triggered_strategy_mode(sweep: SweepEvent | None) -> str:
    if sweep is not None and sweep.volume_crack_confluence and sweep.number_theory_confluence:
        return "LIQ_VP_NT_FVG_A_PLUS"
    return "LIQ_VP_NT_FVG_SCALP"


def ema_trade_filter(
    ema_contexts: dict[str, dict[str, Any]],
    direction: DirectionWord | None,
    sweep_ok: bool,
    m5_structure: bool,
    fvg_after_sweep: bool,
) -> dict[str, Any]:
    if direction is None:
        return {"passes": False, "present": [], "missing": []}
    desired = "bullish" if direction == "BUY" else "bearish"
    opposite = "bearish" if desired == "bullish" else "bullish"
    present: list[str] = []
    missing: list[str] = []
    dominant = [ema_contexts.get(tf, {}).get("ema_alignment") for tf in ("M15", "H1", "H4")]
    if desired in dominant:
        present.append("ema_bullish_alignment" if desired == "bullish" else "ema_bearish_alignment")
        return {"passes": True, "present": present, "missing": missing}
    if dominant.count(opposite) >= 2:
        missing.append("countertrend_vs_ema_requires_extra_confirmation")
        if sweep_ok and m5_structure and fvg_after_sweep:
            present.append("countertrend_extra_confirmation_present")
            return {"passes": True, "present": present, "missing": missing}
        return {"passes": False, "present": present, "missing": missing}
    present.append("ema_mixed_range")
    return {"passes": True, "present": present, "missing": missing}


def rsi_trade_filter(rsi_contexts: dict[str, dict[str, Any]], direction: DirectionWord | None) -> dict[str, list[str]]:
    if direction is None:
        return {"present": [], "missing": []}
    present: list[str] = []
    missing: list[str] = []
    for timeframe in ("M15", "M5"):
        ctx = rsi_contexts.get(timeframe, {})
        warning = ctx.get("rsi_warning")
        if warning in {"rsi_bullish_momentum", "rsi_bearish_momentum", "rsi_overbought_exhaustion_possible", "rsi_oversold_exhaustion_possible"}:
            if direction == "BUY" and warning == "rsi_bearish_momentum":
                missing.append("rsi_bearish_momentum_against_long")
            elif direction == "SELL" and warning == "rsi_bullish_momentum":
                missing.append("rsi_bullish_momentum_against_short")
            else:
                present.append(warning)
    return {"present": present, "missing": missing}


def build_htf_context(
    frames: dict[str, pd.DataFrame],
    price: float,
    *,
    ema_contexts: dict[str, dict[str, Any]] | None = None,
    rsi_contexts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    h1 = _closed_frame(frames.get("H1"))
    h4 = _closed_frame(frames.get("H4"))
    return {
        "h1_bias": infer_bias(h1),
        "h4_bias": infer_bias(h4),
        "premium_discount": infer_premium_discount(h1 if not _frame_empty(h1) else h4, price),
        "quarterly_block": "not_configured",
        "ema": {tf: (ema_contexts or {}).get(tf) for tf in ("H1", "H4", "D1") if (ema_contexts or {}).get(tf)},
        "rsi": {tf: (rsi_contexts or {}).get(tf) for tf in ("H1", "H4", "D1") if (rsi_contexts or {}).get(tf)},
        "role": "H4/H1 context only; M15/M5/M1 required for scalping signal",
    }


def build_intraday_context(
    frames: dict[str, pd.DataFrame],
    price: float,
    *,
    ema_contexts: dict[str, dict[str, Any]] | None = None,
    rsi_contexts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
        "ema": {tf: (ema_contexts or {}).get(tf) for tf in ("M1", "M5", "M15") if (ema_contexts or {}).get(tf)},
        "rsi": {tf: (rsi_contexts or {}).get(tf) for tf in ("M1", "M5", "M15") if (rsi_contexts or {}).get(tf)},
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
    volume_profile_source: str = "intraday_fallback",
) -> dict[str, Any]:
    m15 = _closed_frame(frames.get("M15"))
    liquidity_pools = pools or []
    sweep_events = sweeps or []
    profile_context = _anchored_volume_profile_context(frames, volume_profile, volume_profile_source)
    if _frame_empty(m15):
        return {
            "external": "unknown",
            "internal": "unknown",
            "price": price,
            "pools": [pool.__dict__ | {"distance_band": pool.distance_band} for pool in liquidity_pools[:20]],
            "sweeps": [event.__dict__ for event in sweep_events[:10]],
            "volume_profile_source": volume_profile_source,
            "volume_profiles": profile_context,
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
        "volume_profile_source": volume_profile_source,
        "volume_profiles": profile_context,
    }


def _anchored_volume_profile_context(frames: dict[str, pd.DataFrame], primary_profile: Any | None, primary_source: str) -> dict[str, Any]:
    intraday = frames.get("M5") if not _frame_empty(frames.get("M5")) else frames.get("M15", pd.DataFrame())
    out: dict[str, Any] = {
        "daily": primary_profile.__dict__ if primary_profile is not None else None,
        "daily_source": primary_source,
    }
    d1 = _closed_frame(frames.get("D1"))
    if not _frame_empty(d1) and len(d1) >= 2:
        previous = d1.iloc[-2]
        out["previous_day"] = _profile_for_range(float(previous["l"]), float(previous["h"]), intraday)
    for timeframe in ("H1", "H4"):
        frame = _closed_frame(frames.get(timeframe))
        if not _frame_empty(frame):
            lookback = frame.tail(min(len(frame), 80))
            out[f"{timeframe.lower()}_swing"] = _profile_for_range(float(lookback["l"].min()), float(lookback["h"].max()), intraday)
    m15 = _closed_frame(frames.get("M15"))
    if not _frame_empty(m15):
        recent = m15.tail(min(len(m15), 120))
        out["external_internal_liquidity_range"] = _profile_for_range(float(recent["l"].min()), float(recent["h"].max()), intraday)
    return out


def _profile_for_range(low: float, high: float, intraday: pd.DataFrame) -> dict[str, Any] | None:
    if _frame_empty(intraday) or high <= low:
        return None
    profile = build_daily_anchored_profile(low, high, intraday)
    return profile.__dict__


def build_session_candle_context(
    *,
    symbol: str,
    frames: dict[str, pd.DataFrame],
    session_name: str,
    time_context: Any,
    ema_contexts: dict[str, dict[str, Any]],
    vwap_data: dict | None,
    liquidity_pools: list[dict],
) -> dict[str, Any]:
    m5 = _closed_frame(frames.get("M5"))
    if _frame_empty(m5):
        return {"classification": "NO_CLEAR_SESSION_BEHAVIOUR", "reason_codes": ["m5_unavailable"]}
    references = build_reference_ranges(frames)
    event = classify_session_candle(
        symbol=symbol,
        timeframe="M5",
        candle=m5.iloc[-1],
        lower_tf=frames.get("M1"),
        session_name=session_name,
        time_context=time_context,
        reference_ranges=references,
        ema_context=ema_contexts.get("M5"),
        vwap_context=vwap_data,
        liquidity_pools=liquidity_pools,
    )
    return event.to_dict()


def build_reference_ranges(frames: dict[str, pd.DataFrame]) -> dict[str, float | None]:
    m15 = normalize_frame(frames.get("M15", pd.DataFrame()))
    d1 = normalize_frame(frames.get("D1", pd.DataFrame()))
    refs: dict[str, float | None] = {}
    if not _frame_empty(m15) and "time" in m15.columns:
        times = pd.to_datetime(m15["time"], utc=True)
        asia = m15[(times.dt.hour >= 0) & (times.dt.hour < 7)]
        london = m15[(times.dt.hour >= 7) & (times.dt.hour < 13)]
        if len(asia):
            refs["asia_high"] = float(asia["h"].max())
            refs["asia_low"] = float(asia["l"].min())
        if len(london):
            refs["london_high"] = float(london["h"].max())
            refs["london_low"] = float(london["l"].min())
    if not _frame_empty(d1) and len(d1) >= 2:
        refs["previous_day_high"] = float(d1["h"].iloc[-2])
        refs["previous_day_low"] = float(d1["l"].iloc[-2])
    return refs


def time_behaviour_filter(
    time_context: dict[str, Any],
    session_event: dict[str, Any],
    displacement: bool,
    structure: bool,
) -> dict[str, Any]:
    present: list[str] = []
    missing: list[str] = []
    penalty = 0
    classification = session_event.get("classification")
    time_window = time_context.get("time_window")
    reasons = set(time_context.get("reason_codes", []))
    if classification in {"OPEN_MANIPULATION_BUY_SIDE_SWEEP", "OPEN_MANIPULATION_SELL_SIDE_SWEEP", "NY_MANIPULATION_REVERSAL_SHORT", "NY_MANIPULATION_REVERSAL_LONG"}:
        present.append("london_open_manipulation_candidate" if "london_open_window" in reasons else "ny_open_manipulation_candidate")
        missing.append("session_open_no_entry_yet")
        return {"passes": False, "present": present, "missing": missing, "score_penalty": 20}
    if classification in {"OPEN_DRIVE_CONTINUATION_LONG", "OPEN_DRIVE_CONTINUATION_SHORT", "ACCEPTED_BREAKOUT_LONG", "ACCEPTED_BREAKOUT_SHORT"}:
        present.append("open_drive_continuation_detected")
        return {"passes": True, "present": present, "missing": missing, "score_penalty": 0}
    if classification == "LIQUIDITY_SEARCH_NO_TRADE":
        missing.append("liquidity_search_no_trade")
        return {"passes": displacement and structure, "present": present, "missing": missing, "score_penalty": 25}
    if time_window == "midday":
        missing.append("midday_chop_risk")
        penalty = 10
    if time_context.get("no_trade_risk") == "high" and not (displacement and structure):
        missing.append("time_window_requires_extra_confirmation")
        return {"passes": False, "present": present, "missing": missing, "score_penalty": max(penalty, 15)}
    present.append("time_behaviour_supports_trade")
    return {"passes": True, "present": present, "missing": missing, "score_penalty": penalty}


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
    rank = {"TRIGGERED": 7, "CONFIRMED_SWEEP": 6, "SWEEPING_INTRABAR": 5, "ARMED": 4, "APPROACHING": 3, "accepted_breakout": 2, "WATCH": 1}
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
    direction_reason = "possible_short_after_buy_side_sweep" if trade_direction == "SHORT" else "possible_long_after_sell_side_sweep"
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
            "possible_direction": f"{trade_direction} candidate",
            "direction_reason": direction_reason,
        },
    )
    rr_payload = build_risk_targets(zone, trade_direction, config, symbol=symbol, vwap_data=liquidity.get("vwap"), liquidity_pools=liquidity.get("pools", []), volume_profile=liquidity.get("volume_profile"))
    confluence = evaluate_primary_confluence(sweep, zone, htf_allows_direction(htf_context, direction), sweep.displacement_after_sweep, sweep.choch_after_sweep)
    zone.metadata["primary_confluence"] = {
        "passed": confluence.passed,
        "present": confluence.reasons_present,
        "missing": confluence.reasons_missing,
    }
    if forced_state == "TRIGGERED" and not confluence.passed:
        forced_state = "ARMED"
        zone.state = "ARMED"
        rejection_reasons.extend([*confluence.reasons_missing, "primary_confluence_incomplete"])
    setup_type = "REVERSAL_SHORT" if trade_direction == "SHORT" else "REVERSAL_LONG"
    if sweep.accepted_breakout:
        setup_type = "TREND_FOLLOWING_SHORT" if trade_direction == "SHORT" else "TREND_FOLLOWING_LONG"
    if forced_state == "TRIGGERED":
        setup_type = _triggered_strategy_mode(sweep)
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
            "confirmations_present": _dedupe_reason_codes([*sweep.reason_codes, "primary_confluence_chain"]) if forced_state == "TRIGGERED" and confluence.passed else [],
            "confirmations_missing": rejection_reasons if forced_state != "TRIGGERED" else [],
            "possible_direction": f"{trade_direction} candidate",
        },
        liquidity=liquidity,
        primary_zone=zone,
        entry_area=rr_payload["entry_area"],
        entry=rr_payload["entry"],
        stop=rr_payload["stop"],
        targets=rr_payload["targets"] if forced_state in {"TRIGGERED", "REENTRY_VALID"} else [],
        theoretical_targets=rr_payload["theoretical_targets"],
        target_candidates=rr_payload["target_candidates"],
        target_clusters=rr_payload["target_clusters"],
        target_validation=rr_payload["target_validation"],
        invalidation=rr_payload["stop"],
        reason_codes=_dedupe_reason_codes([direction_reason, *sweep.reason_codes, *(["primary_confluence_chain"] if confluence.passed else [])]),
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
    if not target_validation_passes(rr_payload["target_validation"], config) and forced_state == "TRIGGERED":
        decision.state = "ARMED"
        decision.rejection_reasons.extend(rr_payload["target_validation"]["reason_codes"])
    _apply_execution_gates(decision, price)
    _sync_non_operational_targets(decision)
    return decision


__all__ = [
    "InteractionResult",
    "PrimaryConfluenceResult",
    "ScalpingConfig",
    "SignalDeduplicator",
    "apply_interactions",
    "build_zones",
    "choose_primary_zone",
    "detect_zone_interactions_since_last_scan",
    "evaluate_primary_confluence",
    "evaluate_scalping_setup",
    "apply_execution_gates",
    "score_setup",
]
