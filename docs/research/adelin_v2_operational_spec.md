# Adelin v2 Operational Specification — Multi-Timeframe Liquidity Reaction Reversal Model

Status: research-only. This specification defines the intended Adelin v2 model and the evidence future research must collect before any implementation discussion.

## 1. Current Status

Old Adelin remains research-only. The old score is not trusted, the old continuation mode is considered toxic, and old historical metrics must not be used as proof that the real discretionary Adelin idea is invalid.

This spec does not re-enable Adelin live. It does not create Telegram signals, broker execution, or deployment permission. `ADELIN_LIVE_ENABLED=false` and continuation safety blocks remain part of the expected safety posture.

## 2. Core Thesis

Adelin v2 is a multi-timeframe liquidity reaction reversal model on XAUUSD.

It seeks high-quality reversal entries after important liquidity is taken into a pre-existing reaction zone. The edge thesis is the relationship between liquidity consumption, the quality of the reaction zone, and immediate post-entry reaction. It is not a generic sweep entry and not a continuation engine.

## 3. Strategy Identity

Adelin is not:

- a generic sweep strategy,
- a generic continuation strategy,
- a gap strategy,
- a fixed TP scalper,
- an indicator strategy.

Adelin is:

- liquidity-first,
- multi-timeframe,
- reaction-zone based,
- reversal-first,
- tight-stop,
- runner-oriented.

## 4. Timeframes

Daily and H4 define major context: major swing liquidity, broad internal/external liquidity, higher-timeframe bias, and volume profile context.

H1 and M15 define intermediate tradable structure: ranges, local swing liquidity, nearer targets, and the difference between shallow and meaningful liquidity.

M5 and M1 define execution detail: the sweep, the touch of the reaction zone, immediate reaction quality, accumulation after entry, and early invalidation behavior.

The v2 model requires the timeframes to agree enough to make the sweep meaningful. A sweep of a tiny M1 level is not equivalent to a sweep into aligned H4/H1/M15 liquidity and reaction context.

## 5. Liquidity Model

HTF internal liquidity is liquidity inside a higher-timeframe range, such as resting stops above or below internal swings.

HTF external liquidity is liquidity outside a higher-timeframe range or beyond major swing extremes.

LTF internal liquidity is local M15/M5/M1 liquidity inside the execution range.

LTF external liquidity is local liquidity outside the execution range, often marking a short-term expansion target or sweep point.

Shallow liquidity is a nearby internal pool that is likely to be taken before price seeks deeper liquidity or a better reaction zone. Shallow sweeps are dirty when deeper uncollected liquidity remains more plausible.

Deep liquidity is a more important pool aligned with higher-timeframe structure or a stronger reaction area.

Target liquidity is the next liquidity pool that can reasonably serve as a runner target.

Already-consumed liquidity is a pool already swept or traded through enough that it should not be counted as fresh target evidence.

Uncollected liquidity is a remaining pool that can still attract price after an initial reversal or failed drive.

## 6. Reaction Zone Model

FVG means a fair value gap that can serve as a reaction zone when liquidity is taken into it.

IFVG means an inverted fair value gap. In v2 it is mainly a reaction-zone concept; rare continuation use is future research only.

Volume crack means a zone where the volume structure suggests an air pocket, low participation area, or imbalance that can create a sharp reaction.

Volume profile swing high/low means a swing or profile-derived level that marks meaningful auction structure.

Old rejection zone means a previously validated rejection area. It must be old enough and structurally meaningful, not created minutes ago and immediately retested.

Old range rejection means a prior range boundary or rejection range that remains relevant as a reaction zone.

Number theory level means an important price ending in 0, such as 4900, 4910, or 4830.

Invalid fresh rejection zone means a rejection zone created only minutes earlier and immediately retested. This is not a clean v2 reaction zone without additional evidence.

## 7. Number Theory

Adelin v2 treats levels ending in 0, such as 4900, 4910, and 4830, as possible confluence. The level must be near the sweep/reaction area and should support a broader liquidity and reaction-zone thesis.

Number theory is never a standalone signal.

## 8. Valid Reversal Setup

A valid reversal setup requires:

- important liquidity taken,
- a reaction zone at or beyond the sweep,
- multi-timeframe liquidity alignment,
- a feasible stop loss not exceeding roughly 40 pips,
- target liquidity or a next likely reaction/reversal zone,
- no gap contamination,
- no shallow-liquidity trap,
- no generic continuation framing.

The best setup has HTF internal or external liquidity taken, LTF liquidity also meaningful at or near the same zone, and a valid reaction zone below or above that liquidity. Entry occurs when liquidity is swept and the reaction zone is touched.

## 9. Invalid / Dirty Setup Rules

Invalid or dirty setups include:

- Asian open gaps,
- weekend or new-week gaps,
- fresh rejection zones created minutes ago and immediately retested,
- shallow internal liquidity when deeper liquidity or a better reaction zone is more likely,
- no target liquidity or next reaction zone,
- price accumulating after rejection instead of reacting,
- no immediate reaction after entry,
- continuation trades, except for the rare future IFVG continuation research case.

## 10. Entry Model

Entry happens after liquidity is taken and the reaction zone is touched. The model does not wait for full confirmation because confirmation often appears after the optimal entry.

That early entry requirement makes post-entry behavior central. Price must react quickly. If it stalls, accumulates, or immediately rejects the premise, the setup quality degrades.

## 11. Stop Loss Model

Normal stop loss is around 20 pips. The maximum is around 40 pips.

The stop should sit behind the local min/max of the reaction zone. A trade is invalid when the required stop exceeds the maximum or when the local structure cannot be protected cleanly.

## 12. Trade Management

After a strong reaction around 100 pips, stop management can move toward break-even.

Adelin is runner-oriented. The trade should be managed toward the next liquidity or next likely reaction zone, not toward a random fixed TP.

Early close is valid research behavior when price accumulates too much after entry, when there is no follow-through, or when price moves back toward break-even and creates a strong opposite M1 engulfing.

No partials are taken under 1 lot. At 1 lot or above, a partial around 50% near halfway to final TP can be considered.

## 13. TP Model

The target is next liquidity or a level before the next likely reaction/reversal zone. TP should be placed before that zone, not inside a likely reversal area.

Adelin v2 is not a fixed random TP scalper. The rare continuation scalp concept belongs to a future module and is not active in this branch.

## 14. News

News should not be blindly avoided. The intended discretionary idea may exploit news-driven liquidity and reaction.

For research and backtest, news must be tagged separately. A news-time paper edge cannot be trusted without spread, slippage, and execution-quality modeling.

## 15. Relationship With Strategy 2 And Strategy 3

Strategy 2 remains separate.

Strategy 3 remains separate.

This branch must not touch Strategy 2, Strategy 3, VWAP, cooldown logic, scanner logic, or market data. Adelin v2 may later become a reaction engine, but this branch only defines and audits the intended model.

## 16. Required Future Validation Path

The required path is:

1. spec and audit foundation,
2. visual review pack,
3. labeled examples,
4. limited backtest with v2-specific context fields,
5. paper shadow scanner,
6. spread/slippage/news execution model,
7. only then discuss live deployment.

This branch is step 1 only. It is not validation that Adelin v2 works.
