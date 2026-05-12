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
    max_spread_pips: float = 30.0

    orderflow_provider: str = "mt5_dom"
    orderflow_symbol: str = "XAUUSD"
    orderflow_confidence_level: str = "LOW"

    ledger_db_path: str = "data/dazro_ledger.sqlite"
    log_level: str = "INFO"

    send_watch_alerts: bool = False
    send_approaching_alerts: bool = True
    send_armed_reaction_alerts: bool = True
    send_sweep_intrabar_alerts: bool = True
    min_reaction_distance_pips: float = 80.0
    approaching_alert_distance_pips: float = 150.0
    armed_alert_distance_pips: float = 80.0
    imminent_reaction_distance_pips: float = 50.0
    allow_far_prep_alerts: bool = True
    far_prep_alert_distance_pips: float = 250.0
    max_far_prep_alerts_per_session: int = 1
    reaction_alert_cooldown_minutes: int = 20
    max_alerts_per_zone_per_session: int = 3
    max_reaction_alerts_per_session: int = 5
    send_triggered_only: bool = False

    min_normal_reaction_target_pips: float = 50.0
    preferred_reaction_target_pips: float = 100.0
    allow_vwap_1r_target: bool = True
    min_vwap_target_pips: float = 30.0
    min_rr_normal: float = 1.5
    min_rr_vwap_scalp: float = 1.0

    enable_reentry_analysis: bool = True
    reentry_max_wait_minutes: int = 30
    reentry_require_new_entry: bool = True
    reentry_require_choch: bool = True
    reentry_require_fvg_or_ifvg: bool = True
    reentry_max_volatility_state: str = "elevated"
    reentry_no_chase_max_distance_pips: float = 80.0

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
            max_spread_pips=_float("MAX_SPREAD_PIPS", 30.0),
            orderflow_provider=os.getenv("ORDERFLOW_PROVIDER", "mt5_dom"),
            orderflow_symbol=os.getenv("ORDERFLOW_SYMBOL", os.getenv("MT5_SYMBOL", "XAUUSD")),
            orderflow_confidence_level=os.getenv("ORDERFLOW_CONFIDENCE_LEVEL", "LOW"),
            ledger_db_path=os.getenv("LEDGER_DB_PATH", "data/dazro_ledger.sqlite"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            send_watch_alerts=_bool(os.getenv("SEND_WATCH_ALERTS"), False),
            send_approaching_alerts=_bool(os.getenv("SEND_APPROACHING_ALERTS"), True),
            send_armed_reaction_alerts=_bool(os.getenv("SEND_ARMED_REACTION_ALERTS"), True),
            send_sweep_intrabar_alerts=_bool(os.getenv("SEND_SWEEP_INTRABAR_ALERTS"), True),
            min_reaction_distance_pips=_float("MIN_REACTION_DISTANCE_PIPS", 80.0),
            approaching_alert_distance_pips=_float("APPROACHING_ALERT_DISTANCE_PIPS", 150.0),
            armed_alert_distance_pips=_float("ARMED_ALERT_DISTANCE_PIPS", 80.0),
            imminent_reaction_distance_pips=_float("IMMINENT_REACTION_DISTANCE_PIPS", 50.0),
            allow_far_prep_alerts=_bool(os.getenv("ALLOW_FAR_PREP_ALERTS"), True),
            far_prep_alert_distance_pips=_float("FAR_PREP_ALERT_DISTANCE_PIPS", 250.0),
            max_far_prep_alerts_per_session=_int("MAX_FAR_PREP_ALERTS_PER_SESSION", 1),
            reaction_alert_cooldown_minutes=_int("REACTION_ALERT_COOLDOWN_MINUTES", 20),
            max_alerts_per_zone_per_session=_int("MAX_ALERTS_PER_ZONE_PER_SESSION", 3),
            max_reaction_alerts_per_session=_int("MAX_REACTION_ALERTS_PER_SESSION", 5),
            send_triggered_only=_bool(os.getenv("SEND_TRIGGERED_ONLY"), False),
            min_normal_reaction_target_pips=_float("MIN_NORMAL_REACTION_TARGET_PIPS", 50.0),
            preferred_reaction_target_pips=_float("PREFERRED_REACTION_TARGET_PIPS", 100.0),
            allow_vwap_1r_target=_bool(os.getenv("ALLOW_VWAP_1R_TARGET"), True),
            min_vwap_target_pips=_float("MIN_VWAP_TARGET_PIPS", 30.0),
            min_rr_normal=_float("MIN_RR_NORMAL", 1.5),
            min_rr_vwap_scalp=_float("MIN_RR_VWAP_SCALP", 1.0),
            enable_reentry_analysis=_bool(os.getenv("ENABLE_REENTRY_ANALYSIS"), True),
            reentry_max_wait_minutes=_int("REENTRY_MAX_WAIT_MINUTES", 30),
            reentry_require_new_entry=_bool(os.getenv("REENTRY_REQUIRE_NEW_ENTRY"), True),
            reentry_require_choch=_bool(os.getenv("REENTRY_REQUIRE_CHOCH"), True),
            reentry_require_fvg_or_ifvg=_bool(os.getenv("REENTRY_REQUIRE_FVG_OR_IFVG"), True),
            reentry_max_volatility_state=os.getenv("REENTRY_MAX_VOLATILITY_STATE", "elevated"),
            reentry_no_chase_max_distance_pips=_float("REENTRY_NO_CHASE_MAX_DISTANCE_PIPS", 80.0),
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

        Path(self.ledger_db_path).parent.mkdir(parents=True, exist_ok=True)
        return ConfigValidation(errors=errors, warnings=warnings)

    def validate(self) -> list[str]:
        return self.validate_runtime().errors


def load_settings(env_file: str | os.PathLike[str] | None = ".env") -> Settings:
    return Settings.from_env(env_file)
