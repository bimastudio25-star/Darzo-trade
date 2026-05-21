----- BEGIN PRE-REGISTERED V3 CRITERIA -----

When a replay is run on Adelin v3 candidates with matched controls:

VERDICT = CONTINUE_REFINEMENT
IF any of (with N >= 30 candidates):
  (a) candidate fast_reaction_rate >= control + 0.10
  (b) candidate runner_rate >= control + 0.07
  (c) candidate fast_sl20_rate <= control - 0.10

VERDICT = STOP_ARCHIVE_V3
IF for all metrics with N >= 30:
  |candidate - control| <= 0.04

VERDICT = INSUFFICIENT_SAMPLE
IF N < 30 candidates.
Default action: pause v3, no further iteration without a different hypothesis.

VERDICT = INCONCLUSIVE
Otherwise. Default action: pause.

----- END PRE-REGISTERED V3 CRITERIA -----
