"""让模型把用户问题转换成可校验的专业 Agent 任务图。"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import calendar
import re
from typing import cast
from zoneinfo import ZoneInfo

from ..config import settings
from ..providers.llm import ModelResponse, create_llm
from ..schemas import TaskPlan, TimeIntent, TimeMode, TimeUnit
from ..sources.universes import SOURCE_UNIVERSES
from .validation import validate_task_plan


PLANNER_INSTRUCTIONS = """你是 Gold Analyst 的任务规划 Agent，只负责分解任务，不调查事实。
根据用户真正要求选择最少但足够的专业 Agent：
- market：价格是多少、涨跌多少、走势、区间变化、行情比较、成交或持仓数值；
- cause：上涨或下跌原因、事件驱动、宏观背景、来源文章调查；
复合问题可以同时选择 market 和 cause；二者没有前后依赖，可以并行。
不得因为问题中出现“上涨”就自动选择 cause；“上涨了多少”主要属于 market。
用户没有指定黄金品种时，market 使用 china_spot。
输入会提供 Asia/Shanghai 的当前日期。不要直接猜测“最近”代表多少天，而要选择时间意图：
- exact_date：用户明确指定单日；
- date_range：用户明确指定起止日期；
- latest_available：用户只说最近、近期、当前行情，没有给窗口长度；
- rolling_window：用户明确说最近 N 天／周／月／年；
- year_to_date：今年以来；
- unspecified：原因调查没有任何时间线索；market 任务不得使用 unspecified。
没有年份的日期按当前年份解释。日期写成 YYYY-MM-DD，不得凭空选择历史年份。
只判断需要哪些专业调查员；系统会固定追加核验任务和依赖关系。
必须调用 submit_task_plan 提交结构化规划，不回答用户问题，不输出私密思维链。
"""


MARKETS = [
    name for name in SOURCE_UNIVERSES
    if name not in {"macro_drivers", "discovery_news"}
]


TASK_PLAN_TOOL = {
    "type": "function",
    "name": "submit_task_plan",
    "description": "提交本次调查的专业 Agent 任务图。",
    "strict": True,
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "needs_market": {"type": "boolean"},
            "needs_cause": {"type": "boolean"},
            "market": {"type": "string", "enum": MARKETS},
            "time_intent": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": [
                            "exact_date", "date_range", "latest_available",
                            "rolling_window", "year_to_date", "unspecified",
                        ],
                    },
                    "anchor_date": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "window_value": {"type": "integer", "minimum": 0},
                    "window_unit": {
                        "type": "string",
                        "enum": ["none", "day", "week", "month", "year"],
                    },
                },
                "required": [
                    "mode", "anchor_date", "start", "end", "window_value", "window_unit",
                ],
            },
        },
        "required": [
            "needs_market", "needs_cause", "market", "time_intent",
        ],
    },
}


@dataclass(frozen=True)
class PlanningResult:
    """工作流既需要计划，也需要保存这次模型调用。"""

    plan: TaskPlan
    response: ModelResponse
    request: dict[str, object]
    model: str


TIME_MODES: set[str] = {
    "exact_date", "date_range", "latest_available", "rolling_window",
    "year_to_date", "unspecified",
}
TIME_UNITS: set[str] = {"none", "day", "week", "month", "year"}


def _current_date() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def _parse_date(value: object, field: str) -> date:
    if not isinstance(value, str) or not value:
        raise ValueError(f"时间意图的 {field} 必须是 YYYY-MM-DD 日期")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"时间意图的 {field} 必须是有效的 YYYY-MM-DD 日期") from exc


def _subtract_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(index, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _resolve_time_intent(
    question: str,
    raw_intent: object,
    today: date,
) -> tuple[TimeIntent, dict[str, str]]:
    """将有限时间意图解析为具体自然日；交易日仍由行情工具决定。"""
    raw = dict(raw_intent) if isinstance(raw_intent, dict) else {}
    mode = raw.get("mode")
    unit = raw.get("window_unit")
    if mode not in TIME_MODES:
        raise ValueError("规划 Agent 返回了未知时间意图")
    if unit not in TIME_UNITS:
        raise ValueError("规划 Agent 返回了未知时间单位")
    window_value = raw.get("window_value")
    if not isinstance(window_value, int) or isinstance(window_value, bool) or window_value < 0:
        raise ValueError("时间窗口必须是非负整数")

    yearless_dates = re.findall(r"(?<!\d)(\d{1,2})月(\d{1,2})日", question)
    has_explicit_year = bool(re.search(r"\d{4}\s*年", question))
    if yearless_dates and not has_explicit_year:
        resolved = [date(today.year, int(month), int(day)) for month, day in yearless_dates]
        if len(resolved) == 1:
            mode = "exact_date"
            anchor = resolved[0]
        else:
            mode = "date_range"
            raw["start"], raw["end"] = resolved[0].isoformat(), resolved[-1].isoformat()
            anchor = resolved[-1]
    else:
        anchor_value = raw.get("anchor_date")
        if not anchor_value and mode in {
            "latest_available", "rolling_window", "year_to_date", "unspecified",
        }:
            anchor_value = today.isoformat()
        anchor = _parse_date(anchor_value, "anchor_date")

    has_numbered_window = bool(re.search(r"(?:最近|近|过去)\s*\d+\s*(?:天|周|个月|月|年)", question))
    if "今天" in question:
        mode = "exact_date"
        anchor = today
    elif any(word in question for word in ("最近", "近期", "当前", "现在")) and not has_numbered_window:
        mode = "latest_available"
        anchor = today

    comparison = "none"
    if mode in {"exact_date", "latest_available"}:
        start = end = anchor
        comparison = "previous_trading_day"
        window_value, unit = 0, "none"
    elif mode == "date_range":
        start = _parse_date(raw.get("start"), "start")
        end = _parse_date(raw.get("end"), "end")
        comparison = "range_start"
        window_value, unit = 0, "none"
    elif mode == "rolling_window":
        if window_value < 1 or unit == "none":
            raise ValueError("rolling_window 必须提供正数窗口和时间单位")
        end = anchor
        if unit == "day":
            start = end - timedelta(days=window_value - 1)
        elif unit == "week":
            start = end - timedelta(days=window_value * 7 - 1)
        elif unit == "month":
            start = _subtract_months(end, window_value)
        else:
            start = _subtract_months(end, window_value * 12)
        comparison = "range_start"
    elif mode == "year_to_date":
        start, end = date(anchor.year, 1, 1), anchor
        comparison = "range_start"
        window_value, unit = 0, "none"
    else:
        start = end = None
        window_value, unit = 0, "none"

    intent = cast(TimeIntent, {
        "mode": cast(TimeMode, mode),
        "anchor_date": anchor.isoformat(),
        "window_value": window_value,
        "window_unit": cast(TimeUnit, unit),
        "comparison": comparison,
    })
    return intent, {
        "start": start.isoformat() if start else "",
        "end": end.isoformat() if end else "",
    }


def _task_goal(agent: str, intent: TimeIntent, time_range: dict[str, str]) -> str:
    if intent["mode"] == "latest_available":
        scope = f"截至 {intent['anchor_date']} 的最近有效交易日，并与前一有效交易日比较"
    elif intent["mode"] == "exact_date":
        scope = f"{intent['anchor_date']} 对应的有效交易日，并与前一有效交易日比较"
    elif time_range["start"] and time_range["end"]:
        scope = f"{time_range['start']} 至 {time_range['end']}"
    else:
        scope = "用户问题指定的时间背景"
    return ("查询黄金价格变化：" if agent == "market" else "调查黄金价格变化原因：") + scope


def generate_task_plan(
    question: str,
    client: object | None = None,
    today: date | None = None,
) -> PlanningResult:
    """让模型做语义派发，固定任务依赖由程序生成。"""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("调查问题不能为空")

    cfg = settings()
    current_date = today or _current_date()
    inputs: list[object] = [{
        "role": "user",
        "content": (
            f"当前日期：{current_date.isoformat()}（Asia/Shanghai）\n"
            f"用户问题：{question.strip()}"
        ),
    }]
    tool_choice = {"type": "function", "name": "submit_task_plan"}
    request = {
        "instructions": PLANNER_INSTRUCTIONS,
        "input": inputs,
        "tools": [TASK_PLAN_TOOL],
        "tool_choice": tool_choice,
    }
    response = create_llm(cfg, client).respond(
        PLANNER_INSTRUCTIONS,
        inputs,
        [TASK_PLAN_TOOL],
        tool_choice,
    )
    calls = [call for call in response.tool_calls if call.name == "submit_task_plan"]
    if len(calls) != 1:
        raise ValueError("规划 Agent 必须且只能提交一个 TaskPlan")

    arguments = calls[0].arguments
    time_intent, time_range = _resolve_time_intent(
        question.strip(), arguments.get("time_intent"), current_date,
    )
    tasks: list[dict[str, object]] = []
    dependency_ids: list[str] = []
    if arguments.get("needs_market") is True:
        tasks.append({
            "id": "market", "agent": "market",
            "goal": _task_goal("market", time_intent, time_range), "depends_on": [],
        })
        dependency_ids.append("market")
    if arguments.get("needs_cause") is True:
        tasks.append({
            "id": "cause", "agent": "cause",
            "goal": _task_goal("cause", time_intent, time_range), "depends_on": [],
        })
        dependency_ids.append("cause")
    tasks.append({
        "id": "verification",
        "agent": "verification",
        "goal": "独立核验全部专业发现的日期、品种、单位、计算、来源独立性与反面解释",
        "depends_on": dependency_ids,
    })
    plan = cast(TaskPlan, {
        "question": question.strip(),
        "market": arguments.get("market"),
        "time_intent": time_intent,
        "time_range": time_range,
        "tasks": tasks,
    })
    return PlanningResult(plan=plan, response=response, request=request, model=cfg["model"])


def create_task_plan(
    question: str,
    client: object | None = None,
    today: date | None = None,
) -> TaskPlan:
    """供独立调用者使用；完整工作流使用 generate_task_plan 保存模型轨迹。"""
    return validate_task_plan(generate_task_plan(question, client, today).plan)
