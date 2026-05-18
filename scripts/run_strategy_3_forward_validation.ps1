param(
    [string]$Symbol = "XAUUSD",
    [string]$ForwardStart = "2026-05-15",
    [string]$DataDir = "data",
    [string]$OutputDir = "backtests/reports/strategy_3_oos_forward_validation"
)

# Strategy 3 forward validation helper.
# This is paper/research backtest validation only.
# Run it after local XAUUSD historical data is updated past 2026-05-14.
# It does not send Telegram live signals, does not place orders, and does not enable live trading.

$ErrorActionPreference = "Stop"

$timeframes = @("M1", "M5", "M15", "H1", "H4", "D1")
$forwardCutoff = [datetime]"2026-05-14"
$latestDates = @()

function Get-LatestTimestamp {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing data file: $Path"
    }

    $lastLine = Get-Content -LiteralPath $Path -Encoding Unicode -Tail 1
    if ([string]::IsNullOrWhiteSpace($lastLine)) {
        throw "Empty data file: $Path"
    }

    $rawTimestamp = (($lastLine -split ",")[0]).Trim()
    [string[]]$formats = @("yyyy.MM.dd HH:mm", "yyyy.MM.dd")
    $parsed = [datetime]::MinValue
    $ok = [datetime]::TryParseExact(
        $rawTimestamp,
        $formats,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::None,
        [ref]$parsed
    )
    if (-not $ok) {
        throw "Could not parse timestamp '$rawTimestamp' in $Path"
    }
    return $parsed
}

foreach ($tf in $timeframes) {
    $path = Join-Path -Path $DataDir -ChildPath (Join-Path -Path $Symbol -ChildPath "$tf.csv")
    $latest = Get-LatestTimestamp -Path $path
    $latestDates += $latest.Date
    Write-Host "$tf latest timestamp: $($latest.ToString('yyyy-MM-dd HH:mm'))"
}

$latestCommonDate = ($latestDates | Sort-Object | Select-Object -First 1)
Write-Host "Latest common available date: $($latestCommonDate.ToString('yyyy-MM-dd'))"

if ($latestCommonDate -le $forwardCutoff) {
    Write-Host "STRATEGY_3_FORWARD_DATA_NOT_AVAILABLE: latest common date is not after 2026-05-14. No backtest run."
    exit 0
}

$env:STRATEGY_3_COOLDOWN_MINUTES = "120"
try {
    python backtest.py `
        --symbol $Symbol `
        --from $ForwardStart `
        --to $latestCommonDate.ToString("yyyy-MM-dd") `
        --timeframes M1,M5,M15,H1,H4,D1 `
        --data-dir $DataDir `
        --output-dir $OutputDir `
        --strategies strategy_3_vwap_1r `
        --fast `
        --progress-every-candles 500
}
finally {
    Remove-Item Env:STRATEGY_3_COOLDOWN_MINUTES -ErrorAction SilentlyContinue
}
