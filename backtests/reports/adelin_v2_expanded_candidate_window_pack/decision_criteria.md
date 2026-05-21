----- BEGIN PRE-REGISTERED CRITERIA -----

CONTEXT:
We will evaluate Adelin v2 candidate detector quality by comparing
candidate metrics vs entry-source-matched + session-matched controls,
stratified by entry source.

Required minimum sample sizes per source for inference:
- SWEEP_EXTREME: candidate N >= 80
- ROUND_LEVEL:   candidate N >= 50
- SWEPT_LIQUIDITY_LEVEL: candidate N >= 50

VERDICT = CONTINUE_DETECTOR_REFINEMENT
IF AT LEAST ONE of the following holds on any source meeting min N:
  (a) candidate fast_reaction_rate >= control fast_reaction_rate + 0.07
  (b) candidate runner_rate (>= 500 pips MFE) >= control runner_rate + 0.05
  (c) candidate fast_sl20_rate <= control fast_sl20_rate - 0.10

VERDICT = STOP_ARCHIVE_DETECTOR
IF FOR ALL sources meeting min N:
  |candidate_fast_reaction - control_fast_reaction| <= 0.03
  AND candidate_fast_sl20_rate >= control_fast_sl20_rate - 0.03
  AND candidate_runner_rate <= control_runner_rate + 0.02

VERDICT = REPEAT_EXPANSION_ONCE
IF effect size (|candidate - control|) >= 0.05 on at least one metric
BUT no source has candidate N >= min N required.
Maximum one repeat. Target on repeat: 500 samples.

VERDICT = INCONCLUSIVE
For any other case. Default action: pause Adelin v2, document, do not iterate.

----- END PRE-REGISTERED CRITERIA -----
