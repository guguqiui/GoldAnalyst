"""专业 Agent 用来提交结构化调查发现的终止型工具。"""
from typing import cast

from ..schemas import Finding
from .base import Tool


STRING = {"type": "string"}
STATUSES = ["supported", "partial", "contradicted", "insufficient"]
AGENTS = ["market", "cause", "verification"]


class SubmitFindingTool(Tool):
    """结束一个专业 Agent 的任务，但不生成面向用户的最终报告。"""

    name = "submit_finding"
    description = "提交当前专业子任务的结构化发现、证据编号和未解决问题。"
    terminal = True
    parameters = {
        "task_id": STRING,
        "agent": {"type": "string", "enum": AGENTS},
        "status": {"type": "string", "enum": STATUSES},
        "summary": STRING,
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": STRING,
                    "value": STRING,
                    "unit": STRING,
                    "note": STRING,
                },
                "required": ["name", "value", "unit", "note"],
            },
        },
        "evidence_ids": {"type": "array", "items": STRING},
        "unresolved": {"type": "array", "items": STRING},
    }

    def execute(self, **finding: object) -> Finding:
        if finding.get("agent") not in AGENTS:
            raise ValueError("未知的专业 Agent")
        if finding.get("status") not in STATUSES:
            raise ValueError("未知的调查状态")

        evidence_ids = finding.get("evidence_ids")
        if not isinstance(evidence_ids, list) or not all(isinstance(item, str) for item in evidence_ids):
            raise ValueError("evidence_ids 必须是字符串数组")
        known_ids = {str(item.get("id")) for item in self.context.run.get("evidence", [])}
        missing = [item for item in evidence_ids if item not in known_ids]
        if missing:
            raise ValueError("专业结论引用了不存在的证据：" + "、".join(missing))

        for field in ("task_id", "summary"):
            if not isinstance(finding.get(field), str) or not str(finding[field]).strip():
                raise ValueError(f"{field} 不能为空")
        facts = finding.get("facts")
        unresolved = finding.get("unresolved")
        if not isinstance(facts, list) or not isinstance(unresolved, list):
            raise ValueError("facts 和 unresolved 必须是数组")
        return cast(Finding, finding)
