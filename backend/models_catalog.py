from __future__ import annotations

from typing import TypedDict


class ModelInfo(TypedDict):
    id: str
    context: int
    blurb: str


MODELS: tuple[ModelInfo, ...] = (
    {
        "id": "MiniMax-M3",
        "context": 1_000_000,
        "blurb": "最新 M 系列语言模型，适用于 Agent 推理、工具调用、代码和长上下文任务（输出速度约 100+ TPS）",
    },
    {
        "id": "MiniMax-M2.7",
        "context": 204_800,
        "blurb": "开启模型的自我迭代（输出速度约 60 TPS）",
    },
    {
        "id": "MiniMax-M2.7-highspeed",
        "context": 204_800,
        "blurb": "M2.7 极速版：效果不变，更快，更敏捷（输出速度约 100 TPS）",
    },
    {
        "id": "MiniMax-M2.5",
        "context": 204_800,
        "blurb": "顶尖性能与极致性价比，轻松驾驭复杂任务（输出速度约 60 TPS）",
    },
    {
        "id": "MiniMax-M2.5-highspeed",
        "context": 204_800,
        "blurb": "M2.5 极速版：效果不变，更快，更敏捷（输出速度约 100 TPS）",
    },
    {
        "id": "MiniMax-M2.1",
        "context": 204_800,
        "blurb": "强大多语言编程能力，全面升级编程体验（输出速度约 60 TPS）",
    },
    {
        "id": "MiniMax-M2.1-highspeed",
        "context": 204_800,
        "blurb": "M2.1 极速版：效果不变，更快，更敏捷（输出速度约 100 TPS）",
    },
    {
        "id": "MiniMax-M2",
        "context": 204_800,
        "blurb": "专为高效编码与 Agent 工作流而生",
    },
)

MODEL_IDS = tuple(item["id"] for item in MODELS)
DEFAULT_MODEL = "MiniMax-M3"


def resolve_model(requested: str | None, fallback: str = DEFAULT_MODEL) -> str:
    model = (requested or fallback or DEFAULT_MODEL).strip()
    if model not in MODEL_IDS:
        raise ValueError(model)
    return model
