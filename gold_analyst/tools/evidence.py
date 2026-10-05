"""从当前子运行读取已经取得的完整证据，不再次访问外部来源。"""
import copy

from .base import Tool


class GetEvidenceTool(Tool):
    name = "get_evidence"
    description = (
        "按 evidence_id 读取本次调查已经保存的完整证据。"
        "仅用于补回 dependency_evidence 中被压缩的正文，不会联网或生成新证据。"
    )
    repeatable = True
    deterministic = True
    parameters = {
        "evidence_id": {"type": "string", "description": "已有证据编号，例如 E3"},
    }

    def execute(self, evidence_id):
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ValueError("evidence_id 不能为空")
        target = evidence_id.strip()
        for item in self.context.run.get("evidence", []):
            if isinstance(item, dict) and item.get("id") == target:
                return copy.deepcopy(item)
        raise ValueError(f"本次调查不存在证据：{target}")
