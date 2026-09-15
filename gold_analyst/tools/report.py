"""终止型工具：模型用它提交结构化核验报告。"""
from .base import Tool
from ..verification import validate_report

STRING = {"type": "string"}


class SubmitReportTool(Tool):
    name = "submit_report"
    description = "提交有证据编号的最终核验报告。"
    terminal = True
    parameters = {
        "title": STRING,
        "summary": STRING,
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "statement": STRING,
                    "verdict": {
                        "type": "string",
                        "enum": ["有证据支持", "部分成立／表述误导", "有证据反驳", "证据不足"],
                    },
                    "reason": STRING,
                    "evidence_ids": {"type": "array", "items": STRING},
                },
                "required": ["statement", "verdict", "reason", "evidence_ids"],
            },
        },
        "unresolved": {"type": "array", "items": STRING},
        "review": STRING,
    }

    def execute(self, **report):
        return validate_report(report, self.context.run["evidence"])
