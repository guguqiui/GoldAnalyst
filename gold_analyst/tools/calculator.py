"""确定性价格计算工具。"""
import json

from .base import Tool
from ..verification import calculate_change


class CalculateChangeTool(Tool):
    name = "calculate_change"
    description = "计算两个正价格的价差和涨跌百分比。不能用计算结果证明输入价格真实性。"
    parameters = {
        "current": {"type": "string"},
        "previous": {"type": "string"},
    }

    def execute(self, current, previous):
        result = calculate_change(current, previous)
        item = self.context.add_evidence(
            "价差与涨跌幅计算",
            json.dumps(result, ensure_ascii=False),
            kind="calculation",
        )
        return {"evidence_id": item["id"], **result}
