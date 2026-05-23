# Strategy 5 Asymmetric Liquidity Reclaim 2R/3R Diagnostic

Research-only diagnostic. No live readiness claim.

## Safety
- Strategy 5 only.
- No Strategy 2/3/4, Adelin, live trading, broker execution, order_send, or Telegram trade alerts.
- XAUUSD CSV files are read-only inputs.
- No optimization or parameter mining.

## Counts
- Candidates: 13056
- Accepted: 29
- Rejected: 13027

## RR Modes
- fixed_2r: accepted=9, target_hit=2, stop_hit=6, still_open_timeout_eod=0
- fixed_3r: accepted=6, target_hit=1, stop_hit=4, still_open_timeout_eod=0
- partial_2r_runner_3r: accepted=6, target_hit=1, stop_hit=4, still_open_timeout_eod=0
- structural_min_2r: accepted=8, target_hit=0, stop_hit=7, still_open_timeout_eod=0

## Rejection Reasons
{
  "NO_CISD_OR_MSS": 1376,
  "NO_DISPLACEMENT_ZONE": 524,
  "NO_RECLAIM": 10856,
  "NO_RETEST_ENTRY": 192,
  "OPPOSING_RESISTANCE_BEFORE_2R": 61,
  "TARGET_BELOW_2R": 18
}

## Splits
- Long/short: `{"LONG": 6216, "SHORT": 6840}`
- Session: `{"asia": 2236, "london": 3220, "ny_am": 3248, "ny_pm": 3644, "rollover": 708}`
- Swept level type: `{"asia_range_high": 1036, "asia_range_low": 992, "h1_swing_high": 100, "h1_swing_low": 68, "london_range_high": 708, "london_range_low": 540, "ny_opening_range_high": 548, "ny_opening_range_low": 548, "previous_day_high": 564, "previous_day_low": 372, "session_midpoint": 3720, "vwap": 3860}`
- Tags: `{"bpr": 0, "cisd": 404, "fvg": 408, "ifvg": 0, "mss": 656}`
- Min RR gate: `{"fail": 12966, "pass": 90}`
- STILL_OPEN/TIMEOUT/EOD distribution included in outcomes: `{"AMBIGUOUS_SAME_CANDLE": 4, "STOP_HIT": 21, "TARGET_HIT": 4}`

## Verdicts
- MECHANICS_BUILT_RESEARCH_ONLY
- REQUIRES_MANUAL_VISUAL_REVIEW
- ASYMMETRIC_RR_PROMISING_REQUIRES_OOS
- MODE_3R_TOO_STRICT
- STRUCTURAL_TARGET_MODE_REQUIRES_REVIEW

## Limitation
This is a deterministic diagnostic approximation of Manipulation -> Reclaim -> Confirmation -> Retest -> Expansion. It is not Strategy 3 with TP stretched, not a 1R strategy, and not deployable.
