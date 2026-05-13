from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

ProviderName = Literal["anthropic", "openai", "none"]


def _bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return float(raw)


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return int(raw)


def _provider(name: str, default: ProviderName) -> ProviderName:
    value = os.getenv(name, default).strip().lower()
    if value not in {"anthropic", "openai", "none"}:
        raise ValueError(f"{name} must be one of: anthropic, openai, none")
    return value  # type: ignore[return-value]


@dataclass(frozen=True)
class ConfigValidation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class Settings:
    paper_mode: bool = True
    demo_execution: bool = False
    live_execution: bool = False
    orderflow_enabled: bool = False
    ai_enabled: bool = True
    telegram_enabled: bool = True

    mt5_login: str = ""
    mt5_password: str = ""
    mt5_server: str = ""
    mt5_path: str = ""
    mt5_symbol: str = "XAUUSD"

    telegram_token: str = ""
    telegram_chat_id: str = ""

    anthropic_api_key: str = ""
    anthropic_fast_model: str = "claude-haiku-4-5-20251001"
    anthropic_deep_model: str = "claude-sonnet-4-20250514"

    openai_api_key: str = ""
    openai_model: str = "gpt-5.5"
    openai_audit_model: str = "gpt-5.5"

    ai_fast_provider: ProviderName = "anthropic"
    ai_deep_provider: ProviderName = "anthropic"
    ai_audit_provider: ProviderName = "openai"

    news_api_key: str = ""
    tavily_api_key: str = ""
    fred_api_key: str = ""

    account_balance: float = 10000.0
    risk_per_trade: float = 0.005
    max_daily_drawdown: float = 0.02
    max_daily_signals: int = 5
    max_consecutive_losses: int = 3
    min_rr: float = 2.0
    max_spread_pips: float = 3.0

    orderflow_provider: str = "mt5_dom"
    orderflow_symbol: str = "XAUUSD"
    orderflow_confidence_level: str = "LOW"

    ledger_db_path: str = "data/dazro_ledger.sqlite"
    log_level: str = "INFO"

    send_watch_alerts: bool = False
    send_approaching_alerts: bool = False
    send_armed_reaction_alerts: bool = False
    send_sweep_intrabar_alerts: bool = False
    min_reaction_distance_pips: float = 50.0
    approaching_alert_distance_pips: float = 150.0
    armed_alert_distance_pips: float = 100.0
    imminent_reaction_distance_pips: float = 50.0
    allow_far_prep_alerts: bool = False
    far_prep_alert_distance_pips: float = 300.0
    max_far_prep_alerts_per_session: int = 1
    reaction_alert_cooldown_minutes: int = 20
    max_alerts_per_zone_per_session: int = 3
    max_reaction_alerts_per_session: int = 5
    send_triggered_only: bool = True

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
    theoretical_sl_buffer_pips: float = 10.0
    min_stop_distance_pips: float = 20.0
    max_stop_distance_pips: float = 150.0
    reaction_cluster_tolerance_pips: float = 100.0
    reaction_cluster_cooldown_minutes: int = 10
    max_confirmed_sweep_alerts_per_cluster: int = 1
    number_theory_tolerance_pips: float = 1.2
    number_theory_strict_pips: float = 0.8
    statistical_scalp_enabled: bool = False
    statistical_scalp_max_per_session: int = 3
    statistical_scalp_min_abs_z: float = 2.0
    statistical_scalp_band_tolerance_pips: float = 0.5

    adelin_enabled: bool = True
    adelin_min_score: int = 65
    adelin_a_plus_score: int = 85
    adelin_vwap_min_score: int = 80
    adelin_sl_min_pips: float = 35.0
    adelin_sl_max_pips: float = 65.0
    adelin_sl_buffer_pips: float = 8.0
    adelin_tp1_rr: float = 2.0
    adelin_tp2_rr: float = 3.0
    adelin_min_scalp_target_pips: float = 50.0
    adelin_ideal_target_pips: float = 100.0
    adelin_min_scalp_rr: float = 1.5
    adelin_a_plus_rr: float = 2.0
    adelin_vp_bins: int = 120
    adelin_vp_crack_ratio: float = 0.15
    adelin_vp_hvn_ratio: float = 0.70
    adelin_min_crack_pips: float = 5.0
    adelin_sweep_min_confidence: float = 0.55
    adelin_liq_match_tolerance_pips: float = 25.0
    adelin_nt_tolerance_pips: float = 15.0
    adelin_session_gate_enabled: bool = True
    adelin_session_windows_utc: str = "08:00-10:30,13:00-17:00"
    adelin_news_gate_enabled: bool = True
    adelin_send_rejection_debug: bool = False
    adelin_send_vwap_research: bool = True

    auto_signal_old_scalping: bool = False
    show_old_scalping_in_analisi: bool = True
    strategy_coordinator_enabled: bool = True
    strategy_a_plus_plus_tolerance_pips: float = 30.0
    strategy_conflict_tolerance_pips: float = 50.0
    send_strategy_conflict_alert: bool = True

    liquidity_expansion_enabled: bool = True
    liquidity_expansion_lookback_h1: int = 60
    liquidity_expansion_range_in_range_max_pips: float = 30.0
    liquidity_expansion_max_per_session: int = 4
    liquidity_expansion_min_rr_tp1: float = 1.0
    liquidity_expansion_max_spread_pips: float = 3.0
    liquidity_expansion_m15_reference_timezone: str = "broker"
    liquidity_expansion_require_risk_ok: bool = True

    enable_reentry_analysis: bool = True
    reentry_max_wait_minutes: int = 30
    reentry_require_new_entry: bool = True
    reentry_require_choch: bool = True
    reentry_require_fvg_or_ifvg: bool = True
    reentry_max_volatility_state: str = "elevated"
    reentry_no_chase_max_distance_pips: float = 8.0

    time_behaviour_enabled: bool = True
    timezone: str = "Europe/Rome"
    broker_time_offset_hours: int = 0
    asia_start: str = "00:00"
    asia_end: str = "07:00"
    pre_london_start: str = "07:00"
    pre_london_end: str = "08:00"
    london_open_start: str = "08:00"
    london_open_end: str = "10:00"
    midday_start: str = "11:00"
    midday_end: str = "13:00"
    pre_ny_start: str = "13:00"
    pre_ny_end: str = "14:30"
    ny_open_start: str = "14:30"
    ny_open_end: str = "16:00"
    ny_pm_start: str = "16:00"
    ny_pm_end: str = "18:00"
    time_behaviour_alerts: bool = False
    session_open_alerts: bool = False
    session_open_alert_cooldown_minutes: int = 20
    session_behaviour_alert_cooldown_minutes: int = 20
    max_session_behaviour_alerts_per_session: int = 3
    send_session_prep_alerts: bool = False
    send_session_manipulation_alerts: bool = False
    send_open_drive_alerts: bool = False

    @classmethod
    def from_env(cls, env_file: str | os.PathLike[str] | None = ".env") -> "Settings":
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()
        return cls(
            paper_mode=_bool(os.getenv("PAPER_MODE"), True),
            demo_execution=_bool(os.getenv("DEMO_EXECUTION"), False),
            live_execution=_bool(os.getenv("LIVE_EXECUTION"), False),
            orderflow_enabled=_bool(os.getenv("ORDERFLOW_ENABLED"), False),
            ai_enabled=_bool(os.getenv("AI_ENABLED"), True),
            telegram_enabled=_bool(os.getenv("TELEGRAM_ENABLED"), True),
            mt5_login=os.getenv("MT5_LOGIN", ""),
            mt5_password=os.getenv("MT5_PASSWORD", ""),
            mt5_server=os.getenv("MT5_SERVER", ""),
            mt5_path=os.getenv("MT5_PATH", ""),
            mt5_symbol=os.getenv("MT5_SYMBOL", "XAUUSD"),
            telegram_token=os.getenv("TELEGRAM_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            anthropic_fast_model=os.getenv("ANTHROPIC_FAST_MODEL", "claude-haiku-4-5-20251001"),
            anthropic_deep_model=os.getenv("ANTHROPIC_DEEP_MODEL", "claude-sonnet-4-20250514"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.5"),
            openai_audit_model=os.getenv("OPENAI_AUDIT_MODEL", "gpt-5.5"),
            ai_fast_provider=_provider("AI_FAST_PROVIDER", "anthropic"),
            ai_deep_provider=_provider("AI_DEEP_PROVIDER", "anthropic"),
            ai_audit_provider=_provider("AI_AUDIT_PROVIDER", "openai"),
            news_api_key=os.getenv("NEWS_API_KEY", ""),
            tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
            fred_api_key=os.getenv("FRED_API_KEY", ""),
            account_balance=_float("ACCOUNT_BALANCE", 10000.0),
            risk_per_trade=_float("RISK_PER_TRADE", 0.005),
            max_daily_drawdown=_float("MAX_DAILY_DRAWDOWN", 0.02),
            max_daily_signals=_int("MAX_DAILY_SIGNALS", 5),
            max_consecutive_losses=_int("MAX_CONSECUTIVE_LOSSES", 3),
            min_rr=_float("MIN_RR", 2.0),
            max_spread_pips=_float("MAX_SPREAD_PIPS", 3.0),
            orderflow_provider=os.getenv("ORDERFLOW_PROVIDER", "mt5_dom"),
            orderflow_symbol=os.getenv("ORDERFLOW_SYMBOL", os.getenv("MT5_SYMBOL", "XAUUSD")),
            orderflow_confidence_level=os.getenv("ORDERFLOW_CONFIDENCE_LEVEL", "LOW"),
            ledger_db_path=os.getenv("LEDGER_DB_PATH", "data/dazro_ledger.sqlite"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            send_watch_alerts=_bool(os.getenv("SEND_WATCH_ALERTS"), False),
            send_approaching_alerts=_bool(os.getenv("SEND_APPROACHING_ALERTS"), False),
            send_armed_reaction_alerts=_bool(os.getenv("SEND_ARMED_REACTION_ALERTS"), False),
            send_sweep_intrabar_alerts=_bool(os.getenv("SEND_SWEEP_INTRABAR_ALERTS"), False),
            min_reaction_distance_pips=_float("MIN_REACTION_DISTANCE_PIPS", 50.0),
            approaching_alert_distance_pips=_float("APPROACHING_ALERT_DISTANCE_PIPS", 150.0),
            armed_alert_distance_pips=_float("ARMED_ALERT_DISTANCE_PIPS", 100.0),
            imminent_reaction_distance_pips=_float("IMMINENT_REACTION_DISTANCE_PIPS", 50.0),
            allow_far_prep_alerts=_bool(os.getenv("ALLOW_FAR_PREP_ALERTS"), False),
            far_prep_alert_distance_pips=_float("FAR_PREP_ALERT_DISTANCE_PIPS", 300.0),
            max_far_prep_alerts_per_session=_int("MAX_FAR_PREP_ALERTS_PER_SESSION", 1),
            reaction_alert_cooldown_minutes=_int("REACTION_ALERT_COOLDOWN_MINUTES", 20),
            max_alerts_per_zone_per_session=_int("MAX_ALERTS_PER_ZONE_PER_SESSION", 3),
            max_reaction_alerts_per_session=_int("MAX_REACTION_ALERTS_PER_SESSION", 5),
            send_triggered_only=_bool(os.getenv("SEND_TRIGGERED_ONLY"), True),
            min_normal_reaction_target_pips=_float("MIN_NORMAL_REACTION_TARGET_PIPS", 50.0),
            preferred_reaction_target_pips=_float("PREFERRED_REACTION_TARGET_PIPS", 100.0),
            allow_vwap_1r_target=_bool(os.getenv("ALLOW_VWAP_1R_TARGET"), True),
            min_vwap_target_pips=_float("MIN_VWAP_TARGET_PIPS", 30.0),
            min_rr_normal=_float("MIN_RR_NORMAL", 1.5),
            min_rr_vwap_scalp=_float("MIN_RR_VWAP_SCALP", 1.0),
            max_official_targets=_int("MAX_OFFICIAL_TARGETS", 3),
            allow_runner_target=_bool(os.getenv("ALLOW_RUNNER_TARGET"), True),
            min_gap_between_official_targets_pips=_float("MIN_GAP_BETWEEN_OFFICIAL_TARGETS_PIPS", 50.0),
            min_gap_between_scalp_targets_pips=_float("MIN_GAP_BETWEEN_SCALP_TARGETS_PIPS", 30.0),
            target_cluster_tolerance_pips=_float("TARGET_CLUSTER_TOLERANCE_PIPS", 25.0),
            min_tp1_distance_pips=_float("MIN_TP1_DISTANCE_PIPS", 50.0),
            min_tp1_distance_pips_vwap_scalp=_float("MIN_TP1_DISTANCE_PIPS_VWAP_SCALP", 30.0),
            hide_micro_targets=_bool(os.getenv("HIDE_MICRO_TARGETS"), True),
            max_candidate_targets_debug=_int("MAX_CANDIDATE_TARGETS_DEBUG", 20),
            show_theoretical_plan_on_watch=_bool(os.getenv("SHOW_THEORETICAL_PLAN_ON_WATCH"), True),
            max_theoretical_targets_on_watch=_int("MAX_THEORETICAL_TARGETS_ON_WATCH", 3),
            theoretical_sl_buffer_pips=_float("THEORETICAL_SL_BUFFER_PIPS", 10.0),
            min_stop_distance_pips=_float("MIN_STOP_DISTANCE_PIPS", 20.0),
            max_stop_distance_pips=_float("MAX_STOP_DISTANCE_PIPS", 150.0),
            reaction_cluster_tolerance_pips=_float("REACTION_CLUSTER_TOLERANCE_PIPS", 100.0),
            reaction_cluster_cooldown_minutes=_int("REACTION_CLUSTER_COOLDOWN_MINUTES", 10),
            max_confirmed_sweep_alerts_per_cluster=_int("MAX_CONFIRMED_SWEEP_ALERTS_PER_CLUSTER", 1),
            number_theory_tolerance_pips=_float("NUMBER_THEORY_TOLERANCE_PIPS", 1.2),
            number_theory_strict_pips=_float("NUMBER_THEORY_STRICT_PIPS", 0.8),
            statistical_scalp_enabled=_bool(os.getenv("STATISTICAL_SCALP_ENABLED"), False),
            statistical_scalp_max_per_session=_int("STATISTICAL_SCALP_MAX_PER_SESSION", 3),
            statistical_scalp_min_abs_z=_float("STATISTICAL_SCALP_MIN_ABS_Z", 2.0),
            statistical_scalp_band_tolerance_pips=_float("STATISTICAL_SCALP_BAND_TOLERANCE_PIPS", 0.5),
            adelin_enabled=_bool(os.getenv("ADELIN_ENABLED"), True),
            adelin_min_score=_int("ADELIN_MIN_SCORE", 65),
            adelin_a_plus_score=_int("ADELIN_A_PLUS_SCORE", 85),
            adelin_vwap_min_score=_int("ADELIN_VWAP_MIN_SCORE", 80),
            adelin_sl_min_pips=_float("ADELIN_SL_MIN_PIPS", 35.0),
            adelin_sl_max_pips=_float("ADELIN_SL_MAX_PIPS", 65.0),
            adelin_sl_buffer_pips=_float("ADELIN_SL_BUFFER_PIPS", 8.0),
            adelin_tp1_rr=_float("ADELIN_TP1_RR", 2.0),
            adelin_tp2_rr=_float("ADELIN_TP2_RR", 3.0),
            adelin_min_scalp_target_pips=_float("ADELIN_MIN_SCALP_TARGET_PIPS", 50.0),
            adelin_ideal_target_pips=_float("ADELIN_IDEAL_TARGET_PIPS", 100.0),
            adelin_min_scalp_rr=_float("ADELIN_MIN_SCALP_RR", 1.5),
            adelin_a_plus_rr=_float("ADELIN_A_PLUS_RR", 2.0),
            adelin_vp_bins=_int("ADELIN_VP_BINS", 120),
            adelin_vp_crack_ratio=_float("ADELIN_VP_CRACK_RATIO", 0.15),
            adelin_vp_hvn_ratio=_float("ADELIN_VP_HVN_RATIO", 0.70),
            adelin_min_crack_pips=_float("ADELIN_MIN_CRACK_PIPS", 5.0),
            adelin_sweep_min_confidence=_float("ADELIN_SWEEP_MIN_CONFIDENCE", 0.55),
            adelin_liq_match_tolerance_pips=_float("ADELIN_LIQ_MATCH_TOLERANCE_PIPS", 25.0),
            adelin_nt_tolerance_pips=_float("ADELIN_NT_TOLERANCE_PIPS", 15.0),
            adelin_session_gate_enabled=_bool(os.getenv("ADELIN_SESSION_GATE_ENABLED"), True),
            adelin_session_windows_utc=os.getenv("ADELIN_SESSION_WINDOWS_UTC", "08:00-10:30,13:00-17:00"),
            adelin_news_gate_enabled=_bool(os.getenv("ADELIN_NEWS_GATE_ENABLED"), True),
            adelin_send_rejection_debug=_bool(os.getenv("ADELIN_SEND_REJECTION_DEBUG"), False),
            adelin_send_vwap_research=_bool(os.getenv("ADELIN_SEND_VWAP_RESEARCH"), True),
            auto_signal_old_scalping=_bool(os.getenv("AUTO_SIGNAL_OLD_SCALPING"), False),
            show_old_scalping_in_analisi=_bool(os.getenv("SHOW_OLD_SCALPING_IN_ANALISI"), True),
            strategy_coordinator_enabled=_bool(os.getenv("STRATEGY_COORDINATOR_ENABLED"), True),
            strategy_a_plus_plus_tolerance_pips=_float("STRATEGY_A_PLUS_PLUS_TOLERANCE_PIPS", 30.0),
            strategy_conflict_tolerance_pips=_float("STRATEGY_CONFLICT_TOLERANCE_PIPS", 50.0),
            send_strategy_conflict_alert=_bool(os.getenv("SEND_STRATEGY_CONFLICT_ALERT"), True),
            liquidity_expansion_enabled=_bool(os.getenv("LIQUIDITY_EXPANSION_ENABLED"), True),
            liquidity_expansion_lookback_h1=_int("LIQUIDITY_EXPANSION_LOOKBACK_H1", 60),
            liquidity_expansion_range_in_range_max_pips=_float("LIQUIDITY_EXPANSION_RANGE_IN_RANGE_MAX_PIPS", 30.0),
            liquidity_expansion_max_per_session=_int("LIQUIDITY_EXPANSION_MAX_PER_SESSION", 4),
            liquidity_expansion_min_rr_tp1=_float("LIQUIDITY_EXPANSION_MIN_RR_TP1", 1.0),
            liquidity_expansion_max_spread_pips=_float("LIQUIDITY_EXPANSION_MAX_SPREAD_PIPS", 3.0),
            liquidity_expansion_m15_reference_timezone=os.getenv("LIQUIDITY_EXPANSION_M15_REFERENCE_TIMEZONE", "broker"),
            liquidity_expansion_require_risk_ok=_bool(os.getenv("LIQUIDITY_EXPANSION_REQUIRE_RISK_OK"), True),
            enable_reentry_analysis=_bool(os.getenv("ENABLE_REENTRY_ANALYSIS"), True),
            reentry_max_wait_minutes=_int("REENTRY_MAX_WAIT_MINUTES", 30),
            reentry_require_new_entry=_bool(os.getenv("REENTRY_REQUIRE_NEW_ENTRY"), True),
            reentry_require_choch=_bool(os.getenv("REENTRY_REQUIRE_CHOCH"), True),
            reentry_require_fvg_or_ifvg=_bool(os.getenv("REENTRY_REQUIRE_FVG_OR_IFVG"), True),
            reentry_max_volatility_state=os.getenv("REENTRY_MAX_VOLATILITY_STATE", "elevated"),
            reentry_no_chase_max_distance_pips=_float("REENTRY_NO_CHASE_MAX_DISTANCE_PIPS", 8.0),
            time_behaviour_enabled=_bool(os.getenv("TIME_BEHAVIOUR_ENABLED"), True),
            timezone=os.getenv("TIMEZONE", "Europe/Rome"),
            broker_time_offset_hours=_int("BROKER_TIME_OFFSET_HOURS", 0),
            asia_start=os.getenv("ASIA_START", "00:00"),
            asia_end=os.getenv("ASIA_END", "07:00"),
            pre_london_start=os.getenv("PRE_LONDON_START", "07:00"),
            pre_london_end=os.getenv("PRE_LONDON_END", "08:00"),
            london_open_start=os.getenv("LONDON_OPEN_START", "08:00"),
            london_open_end=os.getenv("LONDON_OPEN_END", "10:00"),
            midday_start=os.getenv("MIDDAY_START", "11:00"),
            midday_end=os.getenv("MIDDAY_END", "13:00"),
            pre_ny_start=os.getenv("PRE_NY_START", "13:00"),
            pre_ny_end=os.getenv("PRE_NY_END", "14:30"),
            ny_open_start=os.getenv("NY_OPEN_START", "14:30"),
            ny_open_end=os.getenv("NY_OPEN_END", "16:00"),
            ny_pm_start=os.getenv("NY_PM_START", "16:00"),
            ny_pm_end=os.getenv("NY_PM_END", "18:00"),
            time_behaviour_alerts=_bool(os.getenv("TIME_BEHAVIOUR_ALERTS"), False),
            session_open_alerts=_bool(os.getenv("SESSION_OPEN_ALERTS"), False),
            session_open_alert_cooldown_minutes=_int("SESSION_OPEN_ALERT_COOLDOWN_MINUTES", 20),
            session_behaviour_alert_cooldown_minutes=_int("SESSION_BEHAVIOUR_ALERT_COOLDOWN_MINUTES", 20),
            max_session_behaviour_alerts_per_session=_int("MAX_SESSION_BEHAVIOUR_ALERTS_PER_SESSION", 3),
            send_session_prep_alerts=_bool(os.getenv("SEND_SESSION_PREP_ALERTS"), False),
            send_session_manipulation_alerts=_bool(os.getenv("SEND_SESSION_MANIPULATION_ALERTS"), False),
            send_open_drive_alerts=_bool(os.getenv("SEND_OPEN_DRIVE_ALERTS"), False),
        )

    @property
    def risk_per_trade_pct(self) -> float:
        return self.risk_per_trade * 100

    def provider_has_key(self, provider: ProviderName) -> bool:
        if provider == "none":
            return True
        if provider == "openai":
            return bool(self.openai_api_key)
        return bool(self.anthropic_api_key)

    def validate_runtime(self) -> ConfigValidation:
        errors: list[str] = []
        warnings: list[str] = []

        if self.live_execution:
            errors.append("LIVE_EXECUTION must remain false; real-money trading is not supported.")
        if not self.paper_mode and not self.demo_execution:
            errors.append("Unsafe mode: enable PAPER_MODE unless explicitly running demo execution.")
        if self.demo_execution:
            missing = [
                name for name, value in {
                    "MT5_LOGIN": self.mt5_login,
                    "MT5_PASSWORD": self.mt5_password,
                    "MT5_SERVER": self.mt5_server,
                }.items()
                if not value
            ]
            if missing:
                errors.append("DEMO_EXECUTION requires MT5 demo credentials: " + ", ".join(missing))
            if not self.ledger_db_path:
                errors.append("DEMO_EXECUTION requires LEDGER_DB_PATH for auditability.")
        if self.ai_enabled:
            for label, provider in {
                "AI_FAST_PROVIDER": self.ai_fast_provider,
                "AI_DEEP_PROVIDER": self.ai_deep_provider,
                "AI_AUDIT_PROVIDER": self.ai_audit_provider,
            }.items():
                if provider != "none" and not self.provider_has_key(provider):
                    warnings.append(f"{label}={provider} has no API key and will degrade or reject if required.")
        if self.telegram_enabled and (not self.telegram_token or not self.telegram_chat_id):
            warnings.append("TELEGRAM_ENABLED=true but TELEGRAM_TOKEN or TELEGRAM_CHAT_ID is missing; notifications will be skipped.")
        if self.risk_per_trade <= 0 or self.risk_per_trade > 0.02:
            errors.append("RISK_PER_TRADE must be in (0, 0.02].")
        if self.max_daily_drawdown <= 0 or self.max_daily_drawdown > 0.2:
            errors.append("MAX_DAILY_DRAWDOWN must be in (0, 0.2].")
        if self.min_rr <= 0:
            errors.append("MIN_RR must be positive.")
        if self.max_spread_pips <= 0:
            errors.append("MAX_SPREAD_PIPS must be positive.")
        if self.liquidity_expansion_m15_reference_timezone not in {"broker", "Europe/Rome"}:
            errors.append("LIQUIDITY_EXPANSION_M15_REFERENCE_TIMEZONE must be 'broker' or 'Europe/Rome'.")
        if self.liquidity_expansion_min_rr_tp1 <= 0:
            errors.append("LIQUIDITY_EXPANSION_MIN_RR_TP1 must be positive.")

        Path(self.ledger_db_path).parent.mkdir(parents=True, exist_ok=True)
        return ConfigValidation(errors=errors, warnings=warnings)

    def validate(self) -> list[str]:
        return self.validate_runtime().errors


def load_settings(env_file: str | os.PathLike[str] | None = ".env") -> Settings:
    return Settings.from_env(env_file)
