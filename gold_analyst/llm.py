"""OpenAI Responses API 适配层。

Agent 只依赖本文件定义的 ModelResponse 和 ToolCall，不直接理解 SDK 的大型联合类型。
"""
import json
from dataclasses import dataclass, field
from typing import cast

from openai import OpenAI
from openai.types.responses import FunctionToolParam, Response, ResponseInputParam
from openai.types.responses import ToolChoiceFunctionParam, ToolChoiceOptions


ToolChoice = ToolChoiceOptions | ToolChoiceFunctionParam


@dataclass(frozen=True)
class ToolCall:
    """Agent 真正需要的函数调用字段。"""

    id: str
    name: str
    arguments: dict[str, object]


@dataclass
class ModelResponse:
    """把 SDK 响应收敛成 Agent 使用的稳定结构。"""

    history_items: list[object] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class ResponsesLLM:
    """对 OpenAI Responses API 的薄封装。"""

    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model = model

    def respond(
        self,
        instructions: str,
        inputs: list[object],
        tools: list[dict[str, object]],
        tool_choice: ToolChoice = "auto",
    ) -> ModelResponse:
        response = self.client.responses.create(
            model=self.model,
            instructions=instructions,
            input=cast(ResponseInputParam, inputs),
            tools=cast(list[FunctionToolParam], tools),
            tool_choice=tool_choice,
            parallel_tool_calls=True,
            max_output_tokens=3000,
            store=False,
        )
        response = cast(Response, response)
        if response.status != "completed":
            raise ValueError("模型输出未完成，不能将截断的回复作为核验结果")

        calls: list[ToolCall] = []
        for item in response.output:
            if getattr(item, "type", "") != "function_call":
                continue
            name = getattr(item, "name", None)
            arguments = getattr(item, "arguments", None)
            call_id = getattr(item, "call_id", None)
            if not isinstance(name, str) or not isinstance(arguments, str) or not isinstance(call_id, str):
                continue
            decoded: object = json.loads(arguments)
            if not isinstance(decoded, dict):
                raise ValueError("工具参数必须为对象")
            calls.append(ToolCall(call_id, name, cast(dict[str, object], decoded)))

        usage = response.usage
        return ModelResponse(
            history_items=list(response.output),
            tool_calls=calls,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
        )


def create_llm(config: dict[str, str], client: object | None = None) -> ResponsesLLM:
    """创建正式客户端；测试可以传入实现相同接口的假客户端。"""
    if client is None:
        client = OpenAI(
            api_key=config["api_key"],
            base_url=config["base_url"],
            timeout=45,
            max_retries=0,
        )
    return ResponsesLLM(cast(OpenAI, client), config["model"])
