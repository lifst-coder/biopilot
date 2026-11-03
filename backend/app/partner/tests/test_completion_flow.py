"""Completion criterion, end to end over HTTP (rules mode, no API key):

"#024 회수율이 왜 낮나" → Critic judges pre-treatment loss vs matrix effect
indeterminate and names the missing controls → proposals → rejection with a
rationale → asking again reflects the rejection and does not repeat the proposal.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

QUESTION = "#024 회수율이 왜 낮나?"


def test_why_question_reject_and_reask(client: TestClient) -> None:
    # 1. ask — no experiment selected; the code in the question picks #024
    first = client.post("/api/partner/ask", json={"project_id": 1, "question": QUESTION})
    assert first.status_code == 200
    a1 = first.json()
    assert a1["intent"] == "cause" and a1["experiment_id"] == 7 and a1["engine"] == "rules"
    critique = client.get(f"/api/partner/critiques/{a1['critique_id']}").json()
    (assessment,) = critique["assessments"]
    assert assessment["verdict"] == "indeterminate"
    assert "전처리 손실과 매트릭스 효과" in assessment["verdict_reason"]
    assert "구분 불가" in assessment["verdict_reason"]
    missing = {m["id"] for m in assessment["missing_controls"]}
    assert {"pre_post_spike", "matrix_matched_calibration"} <= missing
    assert "판정:" in a1["answer"] and "누락 대조군" in a1["answer"]
    assert "[추정]" in a1["answer"]  # alternative explanations are marked as estimates
    assert any(s["ref_type"] == "partner.Critique" for s in a1["sources"])
    keys = {e["key"] for e in a1["evidence"]}
    assert all(k in keys for s in a1["statements"] for k in s["evidence_keys"])

    # 2. proposals exist; the top-priority one separates loss vs matrix effect
    ranked = client.get(
        "/api/partner/proposals", params={"project_id": 1, "experiment_id": 7, "sort": "priority"}
    ).json()
    top = ranked[0]
    assert top["id"] in a1["proposal_ids"]
    assert top["design"]["template_id"] == "pre_post_spike"

    # 3. reject with a rationale
    rationale = "무농약 블랭크 사과 시료를 확보할 수 없다"
    decided = client.post(
        f"/api/partner/proposals/{top['id']}/decision",
        json={"action": "reject", "rationale": rationale},
    ).json()
    assert decided["status"] == "rejected"
    assert decided["decision"]["constraints"] == ["blank_matrix"]

    # 4. ask again — a new critique reflects the rejection and does not repeat it
    a2 = client.post("/api/partner/ask", json={"project_id": 1, "question": QUESTION}).json()
    assert a2["critique_id"] != a1["critique_id"]
    assert rationale in a2["answer"]
    second = client.get(f"/api/partner/critiques/{a2['critique_id']}").json()
    (fb,) = second["decision_feedback"]
    assert fb["proposal_id"] == top["id"] and fb["applied"] == "alternative_proposed"
    new_props = [client.get(f"/api/partner/proposals/{i}").json() for i in second["proposal_ids"]]
    assert top["signature"] not in {p["signature"] for p in new_props}
    alternative = next(p for p in new_props if top["id"] in p["supersedes_proposal_ids"])
    assert "blank_matrix" not in alternative["design"]["requires"]

    # 5. decision history and stored exchanges
    history = client.get("/api/partner/projects/1/decisions").json()
    assert history["entries"][0]["reflected_in_critique_ids"] == [second["id"]]
    exchanges = client.get("/api/partner/projects/1/exchanges").json()["items"]
    assert [x["id"] for x in exchanges] == [a2["exchange_id"], a1["exchange_id"]]
    assert exchanges[0]["response"]["critique_id"] == a2["critique_id"]

    # 6. asking the same thing with unchanged inputs reuses the stored critique
    a3 = client.post("/api/partner/ask", json={"project_id": 1, "question": QUESTION}).json()
    assert a3["critique_id"] == a2["critique_id"] and "재사용" in a3["answer"]
