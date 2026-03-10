from backend.llm.chat_client import MockChatProvider
from backend.llm.llm_evaluator import LLMEvaluator
from backend.storage.models import LLMEvaluationModel


def test_llm_output_contract_repairs_missing_rules():
    evaluator = LLMEvaluator(MockChatProvider())
    payload = evaluator._repair_payload(
        '{"ticket_id":"INC-12345","rules":[{"rule_id":"ITGC-AC-01","status":"FAIL","confidence":0.8,"why":"bad","evidence":[{"type":"field","ref_id":"field:requestor.id","timestamp":null,"snippet":"u1"}],"recommended_action":"fix","control_mapping":["SOX"]}]}',
        "INC-12345",
        "run-123",
    )

    validated = LLMEvaluationModel.model_validate(payload)

    assert validated.run_id == "run-123"
    assert validated.ticket_id == "INC-12345"
    assert len(validated.rules) == 8
    assert any(rule.rule_id == "ITGC-AC-01" and rule.status == "FAIL" for rule in validated.rules)
    assert any(rule.rule_id == "ITGC-CHG-01" and rule.status == "NEEDS_REVIEW" for rule in validated.rules)
