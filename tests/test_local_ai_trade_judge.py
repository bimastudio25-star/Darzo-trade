from __future__ import annotations

from pathlib import Path

from dazro_trade.analysis.local_ai_trade_judge import (
    LocalAIJudgeConfig,
    LocalAITradeJudge,
    build_judge_prompt,
    parse_ai_judge_json,
)


def test_local_ai_judge_disabled_by_default_config_is_noop():
    judge = LocalAITradeJudge(LocalAIJudgeConfig(enabled=False))
    result = judge.judge({"trade_id": "x"}).to_dict()
    assert result["enabled"] is False
    assert result["status"] == "disabled"


def test_strict_output_parsing_accepts_valid_json():
    result = parse_ai_judge_json(
        """
        {
          "m5_close_quality": "GOOD_CLOSE",
          "reaction_state": "REACTION_ALIVE",
          "retest_quality": "NO_RETEST",
          "runner_opportunity": "STANDARD_TP",
          "suggested_action": "HOLD",
          "confidence": 0.72,
          "reason_codes": ["directional_close"],
          "notes": "research only"
        }
        """
    )
    assert result.status == "ok"
    assert result.m5_close_quality == "GOOD_CLOSE"
    assert result.confidence == 0.72
    assert result.reason_codes == ("directional_close",)


def test_invalid_json_is_handled_safely():
    result = parse_ai_judge_json("not-json")
    assert result.status == "invalid_json"
    assert result.error


def test_invalid_labels_do_not_crash():
    result = parse_ai_judge_json(
        '{"m5_close_quality":"MAGIC","reaction_state":"REACTION_ALIVE","retest_quality":"NO_RETEST","runner_opportunity":"STANDARD_TP","suggested_action":"HOLD","confidence":2}'
    )
    assert result.status == "invalid_labels"
    assert result.m5_close_quality is None
    assert result.confidence == 1.0


def test_prompt_reminds_model_about_research_only_thresholds_and_missing_data():
    prompt = build_judge_prompt({"entry_price": 2400, "m5": []})
    assert "+10/+15/+20 are XAUUSD price movement thresholds" in prompt
    assert "Return JSON only" in prompt
    assert "Do not invent missing data" in prompt
    assert "Do not place orders" in prompt


def test_ai_scaffold_has_no_broker_or_message_send_calls():
    text = Path("dazro_trade/analysis/local_ai_trade_judge.py").read_text(encoding="utf-8")
    assert "order_send(" not in text
    assert ".order_send" not in text
    assert "send_message(" not in text
    assert ".send_message" not in text
