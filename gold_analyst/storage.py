"""每次运行保存一份 JSON 和 Markdown；原始工具证据保留在 JSON 中。"""
from datetime import datetime, timezone
import json
from .config import ROOT


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def markdown(run):
    report = run.get("report", {})
    lines = ["# " + report.get("title", "黄金新闻核验"), "",
             f"模式：{run['mode']} · 时间：{run['created_at']}", "",
             run.get("notice", ""), "", report.get("summary", ""), ""]
    for c in report.get("claims", []):
        lines += ["## " + c["statement"], "", "结论：" + c["verdict"], "",
                  c.get("reason", ""), "", "证据：" + "、".join(c.get("evidence_ids", [])), ""]
    lines += ["## 未解决问题", ""] + ["- " + str(x) for x in report.get("unresolved", [])]
    lines += ["", "## 证据", ""]
    for e in run.get("evidence", []):
        lines += [f"### {e['id']} · {e['title']}", "", f"来源：{e.get('url') or '本地计算/教学材料'}",
                  f"获取时间：{e['retrieved_at']}", "", e.get("text", ""), ""]
        for citation in e.get("citations", []):
            lines += [f"- {citation.get('title', '')}：{citation.get('url', '')}"]
    if run.get("candidates"):
        lines += ["## Multi-Agent 候选", ""]
        for candidate in run["candidates"]:
            candidate_report = candidate.get("report", {})
            lines += [f"### {candidate.get('strategy_name', candidate.get('strategy', '研究员'))}", "",
                      f"状态：{candidate.get('status', 'unknown')} · 证据 {candidate.get('evidence_count', 0)} 条", "",
                      candidate_report.get("summary", candidate.get("error", "未生成报告")), ""]
    lines += ["## 审核", "", report.get("review", "尚未进行模型语义审核。")]
    return "\n".join(lines)


def save_run(run):
    folder = ROOT / "reports"
    folder.mkdir(exist_ok=True)
    (folder / f"{run['id']}.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / f"{run['id']}.md").write_text(markdown(run), encoding="utf-8")
