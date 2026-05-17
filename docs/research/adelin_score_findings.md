# Adelin Existing Score Findings

Status: research-only / live suspended.

No full backtest was run for this lockdown task. The latest score profile used the existing generated reports only.

## Findings

- Existing Adelin score is not predictive: Pearson/Spearman were near zero on Full, IS, and OOS.
- Raising `min_score` should not be used as a fix. The 90+ score bucket performed worse than the main 80-84 bucket.
- Score distribution is too narrow: 988 of 1007 trades were in the 80-84 bucket.
- Continuation is toxic in trade-linked results and should be blocked if Adelin is ever accidentally re-enabled live.
- Rejection improves the full-period profile, but OOS was only break-even, so it is not a deployable live entry trigger.
- `distance_to_liquidity_pips` was missing from the existing CSV/report and is needed for future guardrail research.
- Score components were present inside `score_setup`, but were not previously exposed in generated trade-linked reports. New telemetry support is optional and backward-compatible for future runs only.

## Lockdown

Adelin remains research-only. `ADELIN_LIVE_ENABLED` defaults to `false`, with disabled reason:

`score_not_predictive_low_score_variance_continuation_toxic_rejection_oos_break_even`

`ADELIN_BLOCK_CONTINUATION_ENTRIES` defaults to `true` as defense-in-depth. This is not a new strategy and does not make Adelin deployable.

## Missing Telemetry

Fields prepared for future reports:

- `symbol`
- `current_price`
- `liquidity_price`
- `liquidity_timeframe`
- `liquidity_type`
- `distance_to_liquidity_pips`
- `score_components`
- `score_reason_codes`

Existing historical reports were not regenerated. Old CSV/JSON files will still miss these fields until a future small, bounded profiling run is executed.

## Shared Simulator Metric Revision

`metric_revision_due_to_still_open_policy: true`

Affected strategies:

- `strategy_1_adelin_scalp`
- `strategy_2_liquidity_expansion`
- `any_strategy_using_shared_simulator`

The shared simulator no longer treats unresolved but valid trades as metric-neutral `STILL_OPEN` positions. Future backtests close them at the available close as either `TIMEOUT_CLOSE` or `END_OF_DATA_CLOSE`, so historical Adelin and Strategy 2.0 baselines can change. This is expected and should not be used to reinterpret Adelin as deployable; Adelin remains research-only / locked down.

## Prossimo step di ricerca, in ordine di priorità

1. `fix/strategy-2-still-open`

   Priorità: alta.

   Stima: piccolo task mirato.

   Motivo: Strategy 2.0 ha STILL_OPEN alto che distorce le metriche. Prima bisogna sistemare max_sim_bars / chiusura simulazione / max excursion robusta agli outlier. Solo dopo si può capire se Strategy 2.0 ha edge reale.

2. `feat/strategy-3-vwap-1r`

   Priorità: seconda.

   Motivo: VWAP 1R è un research path promettente, ma va costruito/validato. Non deve partire prima di aver chiarito Strategy 2.0 se questa richiede solo un fix mirato.

3. Adelin rewrite

   Priorità: sospesa.

   Motivo: lo score Adelin attuale non è predittivo. Continuation è tossica. Rejection migliora ma OOS è solo break-even. Il rewrite Adelin va riesaminato solo dopo Strategy 2.0 still-open fix e VWAP 1R research.

## Rationale

Non riscrivere Adelin ora.

Non costruire nuovo Contextual Reaction Engine ora.

Prima sistemare le strategie/ricerche con miglior rapporto tempo-informazione.
