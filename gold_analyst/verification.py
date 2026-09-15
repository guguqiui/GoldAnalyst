"""确定性计算与报告结构审核。这里只验证算术和引用结构，不判断经济因果。"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

VERDICTS = {"有证据支持", "部分成立／表述误导", "有证据反驳", "证据不足"}


def calculate_change(current, previous):
    try:
        current, previous = Decimal(str(current)), Decimal(str(previous))
    except InvalidOperation as exc:
        raise ValueError("请输入有效数字") from exc
    if not current.is_finite() or not previous.is_finite() or current <= 0 or previous <= 0:
        raise ValueError("价格必须为有限正数，不能把零或缺失值作为价格")
    change = current - previous
    pct = change / previous * 100
    return {"current": str(current), "previous": str(previous),
            "difference": str(change.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "percent": str(pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "formula": "(current - previous) / previous × 100",
            "scope": "仅验证输入数字的算术关系；不证明输入价格来自官方或口径相同。"}


def validate_report(report, evidence):
    """拒绝不存在的引用；无证据结论降级。语义是否支持仍需审核员及人工复核。"""
    if not isinstance(report, dict) or not isinstance(report.get("claims"), list):
        raise ValueError("模型未返回要求的核验报告结构")
    for field in ("title", "summary", "review"):
        if not isinstance(report.get(field), str):
            raise ValueError(f"报告缺少文字字段 {field}")
    if not isinstance(report.get("unresolved"), list) or any(not isinstance(x, str) for x in report["unresolved"]):
        raise ValueError("未解决问题必须为文字列表")
    if not 1 <= len(report["claims"]) <= 8:
        raise ValueError("报告需要包含 1–8 条待核验说法")
    by_id = {e["id"]: e for e in evidence}
    notes = []
    for claim in report["claims"]:
        if not isinstance(claim, dict) or not isinstance(claim.get("statement"), str) or not isinstance(claim.get("reason"), str):
            raise ValueError("每条核验必须有文字 statement")
        refs = claim.get("evidence_ids", [])
        if not isinstance(refs, list) or any(not isinstance(r, str) or r not in by_id for r in refs):
            raise ValueError("报告包含不存在的证据编号，已拒绝提交")
        if claim.get("verdict") not in VERDICTS:
            claim["verdict"] = "证据不足"
        if not refs and claim["verdict"] != "证据不足":
            claim["verdict"] = "证据不足"
            notes.append("一条无引用结论已降级为证据不足。")
        if claim["verdict"] in {"有证据支持", "有证据反驳"} and refs:
            if all(by_id[r].get("kind") in {"news", "search"} for r in refs):
                claim["verdict"] = "证据不足"
                notes.append("仅有新闻或搜索线索的确定性结论已降级，需补充独立原始证据。")
    # 检查正文中显式写出的 [E99] 等引用。
    import json
    for ref in re.findall(r"\[(E\d+)\]", json.dumps(report, ensure_ascii=False)):
        if ref not in by_id:
            raise ValueError("报告正文包含不存在的证据引用")
    report["validation_notes"] = notes
    return report
