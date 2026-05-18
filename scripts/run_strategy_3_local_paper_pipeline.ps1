param(
    [string]$Symbol = "XAUUSD",
    [string]$SymbolBroker = "XAUUSD",
    [int]$IntervalMinutes = 15,
    [switch]$Loop,
    [switch]$Apply,
    [string]$FromTimestamp = "",
    [int]$DaysBack = 7
)

# Strategy 3 local paper pipeline.
# This wrapper is data/paper-only: it does not send orders, does not call Telegram,
# and does not enable live trading. Apply mode still only updates local candle CSVs
# after the Python pipeline's validation gates pass.

$ErrorActionPreference = "Stop"

$argsList = @(
    "scripts/run_strategy_3_local_paper_pipeline.py",
    "--symbol", $Symbol,
    "--symbol-broker", $SymbolBroker,
    "--interval-minutes", "$IntervalMinutes",
    "--days-back", "$DaysBack"
)

if ($Loop) {
    $argsList += "--loop"
} else {
    $argsList += "--once"
}

if ($Apply) {
    $argsList += "--apply"
} else {
    $argsList += "--no-apply"
}

if ($FromTimestamp -ne "") {
    $argsList += @("--from-timestamp", $FromTimestamp)
}

python @argsList
exit $LASTEXITCODE
