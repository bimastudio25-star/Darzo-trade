from __future__ import annotations

from datetime import datetime, timezone

from dazro_trade.analysis.targets import TargetCandidate, TargetPolicy, build_official_tp_ladder, cluster_target_candidates
from dazro_trade.core.models import ScalpingDecision, SetupZone
from dazro_trade.core.symbols import price_to_pips
from dazro_trade.notifications.telegram_bot import format_scalping_decision
from dazro_trade.runtime.scanner import ScalpingScanner
from dazro_trade.core.config import Settings


def candidate(price, entry=4706.15, stop=4705.40, source="INTERNAL_LIQUIDITY", basis="internal liquidity", priority=2):
    risk_pips = price_to_pips("XAUUSD", abs(entry - stop))
    distance_pips = price_to_pips("XAUUSD", abs(price - entry))
    return TargetCandidate(
        price=price,
        source=source,
        basis=basis,
        distance_pips=round(distance_pips, 1),
        rr=round(distance_pips / risk_pips, 2),
        quality="high" if source != "R_MULTIPLE" else "medium",
        priority=priority,
        confluences=[basis],
        metadata={},
    )


def ladder(candidates, entry=4706.15, stop=4705.40, direction="LONG", setup_target_type="NORMAL_REACTION"):
    return build_official_tp_ladder(
        symbol="XAUUSD",
        direction=direction,
        entry=entry,
        stop=stop,
        candidates=candidates,
        policy=TargetPolicy(),
        setup_target_type=setup_target_type,
    )


def test_cluster_liquidity_nearby_becomes_one_target():
    candidates = [candidate(4712.34), candidate(4712.38), candidate(4712.41)]
    clusters = cluster_target_candidates(candidates, "XAUUSD", 25)
    out = ladder(candidates)
    assert len(clusters) == 1
    assert len(out["official_targets"]) == 1
    assert out["official_targets"][0]["price"] == 4712.38
    assert out["official_targets"][0]["cluster_range"] == [4712.34, 4712.41]
    assert "targets_clustered_nearby_liquidity" in out["reason_codes"]


def test_micro_tp_hidden_from_official_targets():
    out = ladder([candidate(4706.25)], entry=4706.15, stop=4705.65)
    assert out["official_targets"] == []
    assert "target_too_close_for_official_tp" in out["reason_codes"]
    assert "candidate_target_debug_only" in out["reason_codes"]


def test_normal_tp1_40_pips_invalid():
    out = ladder([candidate(4710.00, entry=4706.0, stop=4705.80)], entry=4706.0, stop=4705.80)
    assert not out["validation"]["valid"]
    assert "official_tp1_too_close" in out["validation"]["reason_codes"]


def test_normal_tp1_70_pips_valid_if_rr_ok():
    out = ladder([candidate(4713.00, entry=4706.0, stop=4705.70)], entry=4706.0, stop=4705.70)
    assert out["validation"]["valid"]
    assert "official_tp1_valid" in out["validation"]["reason_codes"]


def test_preferred_100_pips_target_reason():
    out = ladder(
        [
            candidate(4713.00, entry=4706.0, stop=4705.70),
            candidate(4718.00, entry=4706.0, stop=4705.70, source="EXTERNAL_LIQUIDITY", basis="external liquidity"),
        ],
        entry=4706.0,
        stop=4705.70,
    )
    assert out["validation"]["valid"]
    assert "preferred_reaction_target_100_pips_available" in out["validation"]["reason_codes"]


def test_vwap_scalp_target_35_pips_valid():
    out = ladder(
        [candidate(4703.50, entry=4700.0, stop=4699.70, source="VWAP", basis="VWAP", priority=1)],
        entry=4700.0,
        stop=4699.70,
        setup_target_type="VWAP_1R_SCALP_LONG",
    )
    assert out["validation"]["valid"]
    assert out["validation"]["setup_target_type"] == "VWAP_1R_SCALP"
    assert "vwap_1r_target_valid" in out["validation"]["reason_codes"]


def test_official_target_count_max_three():
    candidates = [candidate(4712.00 + idx * 5.50, entry=4706.0, stop=4705.70) for idx in range(20)]
    out = ladder(candidates, entry=4706.0, stop=4705.70)
    assert len(out["official_targets"]) == 3
    assert all(target["label"] in {"TP1", "TP2", "TP3"} for target in out["official_targets"])


def test_r_multiple_does_not_beat_clean_liquidity_cluster():
    out = ladder(
        [
            candidate(4700.50, entry=4700.0, stop=4699.50, source="R_MULTIPLE", basis="1R mathematical", priority=6),
            candidate(4712.00, entry=4700.0, stop=4699.50, source="EXTERNAL_LIQUIDITY", basis="external liquidity", priority=2),
        ],
        entry=4700.0,
        stop=4699.50,
    )
    assert out["official_targets"][0]["basis"] == "external liquidity"


def test_screenshot_like_candidates_clustered_and_watch_message_theoretical_only():
    candidates = [
        candidate(price, entry=4706.15, stop=4705.60)
        for price in [4706.78, 4707.03, 4707.34, 4707.38, 4707.41, 4707.70, 4708.08, 4709.50]
    ]
    out = ladder(candidates, entry=4706.15, stop=4705.60)
    assert len(out["official_targets"]) <= 3
    assert len(out["target_clusters"]) < len(candidates)

    zone = SetupZone("z", "XAUUSD", "M15", "sell_side_liquidity_sweep", "LTF_SETUP", "WATCH", "BUY", 4705.85, 4706.45)
    decision = ScalpingDecision(
        symbol="XAUUSD",
        setup_type="LIQUIDITY_REACTION",
        direction="LONG",
        state="WATCH",
        score=50,
        confidence=0.5,
        htf_context={},
        intraday_context={"current_price": 4706.10, "confirmations_missing": ["M1/M5 CHOCH"]},
        liquidity={},
        primary_zone=zone,
        entry_area=(4705.85, 4706.45),
        entry=4706.15,
        stop=4705.60,
        targets=[],
        theoretical_targets=out["theoretical_targets"],
        target_validation=out["validation"],
        timestamp_utc=datetime.now(timezone.utc),
    )
    text = format_scalping_decision(decision)
    assert "NO ENTRY" in text
    assert "Target/RR insufficiente" in text
    assert "TP1 teorico" in text
    assert "TP4" not in text


def test_telegram_confirmed_sweep_title_and_theoretical_plan():
    zone = SetupZone(
        "z",
        "XAUUSD",
        "M1",
        "sell_side_liquidity_sweep",
        "LTF_SETUP",
        "CONFIRMED_SWEEP",
        "BUY",
        4707.13,
        4707.63,
        metadata={"liquidity_level": 4707.38, "possible_direction": "LONG candidate"},
    )
    decision = ScalpingDecision(
        symbol="XAUUSD",
        setup_type="LIQUIDITY_REACTION",
        direction="LONG",
        state="CONFIRMED_SWEEP",
        score=70,
        confidence=0.7,
        htf_context={},
        intraday_context={"current_price": 4707.38, "confirmations_missing": ["bullish FVG/IFVG"]},
        liquidity={},
        primary_zone=zone,
        entry_area=(4707.20, 4707.45),
        entry=4707.30,
        stop=4706.70,
        theoretical_targets=[
            {"label": "TP1", "price": 4708.08, "basis": "liquidity cluster", "distance_pips": 78, "rr": 1.3},
        ],
        reason_codes=["possible_long_after_sell_side_sweep", "close_back_inside"],
    )
    text = format_scalping_decision(decision)
    assert "SWEEP CONFERMATA, ASPETTO TRIGGER" in text
    assert "NO ENTRY" in text
    assert "Direzione possibile: LONG candidate" in text
    assert "TP1 teorico" in text


def test_telegram_triggered_shows_max_three_operational_tps():
    decision = ScalpingDecision(
        symbol="XAUUSD",
        setup_type="REVERSAL_LONG",
        direction="LONG",
        state="TRIGGERED",
        score=95,
        confidence=0.95,
        htf_context={},
        intraday_context={},
        liquidity={},
        primary_zone=SetupZone("z", "XAUUSD", "M1", "bullish_fvg", "LTF_SETUP", "TRIGGERED", "BUY", 4706.9, 4707.4),
        entry_area=(4707.20, 4707.45),
        entry=4707.30,
        stop=4706.70,
        targets=[{"label": f"TP{idx}", "price": 4708 + idx, "basis": "liquidity", "distance_pips": 70 + idx, "rr": 1 + idx} for idx in range(1, 6)],
        target_validation={"valid": True, "reason_codes": ["official_tp_ladder_valid", "target_cluster_used"]},
    )
    text = format_scalping_decision(decision)
    assert "XAUUSD — LONG VALID" in text
    assert "TP3" in text
    assert "TP4" not in text


def test_telegram_invalidated_emphasizes_no_entry():
    decision = ScalpingDecision(
        symbol="XAUUSD",
        setup_type="REVERSAL_SHORT",
        direction="SHORT",
        state="INVALIDATED",
        score=0,
        confidence=0,
        htf_context={},
        intraday_context={"current_price": 4725.0},
        liquidity={},
        stop=4722.0,
        invalidation=4722.0,
        rejection_reasons=["current_price_above_short_stop"],
    )
    text = format_scalping_decision(decision)
    assert "SETUP INVALIDATO" in text
    assert "NO ENTRY" in text
    assert "current_price_above_short_stop" in text


def test_reaction_cluster_alert_groups_two_sided_sweeps():
    class Sender:
        def __init__(self):
            self.sent = []

        def send_text(self, text):
            self.sent.append(text)
            return {"ok": True}

    sender = Sender()
    scanner = ScalpingScanner(
        Settings(
            telegram_token="x",
            telegram_chat_id="1",
            reaction_cluster_tolerance_pips=100,
            send_triggered_only=False,
        ),
        telegram_bot=sender,
    )
    decision = ScalpingDecision(
        symbol="XAUUSD",
        setup_type="LIQUIDITY_REACTION",
        direction="WAIT",
        state="CONFIRMED_SWEEP",
        score=60,
        confidence=0.6,
        htf_context={},
        intraday_context={},
        liquidity={
            "pools": [
                {"id": "h", "level": 4705.52, "side": "buy_side", "pool_type": "internal_high", "distance_pips": 20},
                {"id": "l", "level": 4707.38, "side": "sell_side", "pool_type": "internal_low", "distance_pips": 20},
            ],
            "sweeps": [
                {"pool_id": "h", "status": "CONFIRMED_SWEEP", "level": 4705.52, "reason_codes": ["possible_short_after_buy_side_sweep"]},
                {"pool_id": "l", "status": "CONFIRMED_SWEEP", "level": 4707.38, "reason_codes": ["possible_long_after_sell_side_sweep"]},
            ],
        },
    )
    assert scanner._maybe_send_reaction_alert(decision, "London")
    assert not scanner._maybe_send_reaction_alert(decision, "London")
    assert len(sender.sent) == 1
    assert "LIQUIDITY REACTION CLUSTER" in sender.sent[0]
    assert "NO ENTRY" in sender.sent[0]
