"""模型接入层：一个 API Key + 本地向量模型，开箱即用。

分工：
    对话模型 -> 云端 OpenAI 兼容接口（用户填的那个 Key）
    向量模型 -> 本机 fastembed（onnxruntime，不需要 torch，不需要第二个 Key）

本地模型通过 HF 镜像（hf-mirror.com）下载，一次下完永久离线可用。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from llama_index.core import Settings
from llama_index.embeddings.openai import OpenAIEmbedding

from config import (
    DEFAULT_LOCAL_EMBED,
    DEFAULT_PROVIDER,
    HF_MIRROR,
    MODEL_DIR,
    PROVIDERS,
    SETTINGS_FILE,
)

# 默认供应商的预设，直接当成 ModelSettings 的出厂值：
# 打开界面时除了 api_key 之外一切都已经配好。
_DEFAULT_PROVIDER_INFO = PROVIDERS[DEFAULT_PROVIDER]
_DEFAULT_LLM = (_DEFAULT_PROVIDER_INFO["llm_models"] or [""])[0]


@dataclass
class ModelSettings:
    """用户在侧栏填的全部模型相关配置。

    出厂值即"可用状态"：向量模型默认走本地（不需要任何 Key），
    对话模型预置了供应商和模型名，用户只需要补一个 api_key。
    """

    provider: str = DEFAULT_PROVIDER
    api_key: str = ""
    base_url: str = _DEFAULT_PROVIDER_INFO["base_url"]
    llm_model: str = _DEFAULT_LLM

    # 向量来源："local" 用本机 fastembed，"api" 用云端 OpenAI 兼容接口
    embed_source: str = "local"
    embed_model: str = DEFAULT_LOCAL_EMBED
    # embed_source="api" 时，允许单独指定 embedding 的地址与 Key
    embed_api_key: str = ""
    embed_base_url: str = ""

    temperature: float = 0.1
    max_tokens: int = 1024
    extra: dict = field(default_factory=dict)

    # -- 派生属性 ---------------------------------------------------------
    @property
    def effective_embed_key(self) -> str:
        return (self.embed_api_key or self.api_key).strip()

    @property
    def effective_embed_base(self) -> str:
        return (self.embed_base_url or self.base_url).strip()

    @property
    def llm_ready(self) -> bool:
        return bool(self.api_key and self.base_url and self.llm_model)

    @property
    def embed_ready(self) -> bool:
        if not self.embed_model:
            return False
        if self.embed_source == "local":
            # 本地模型不需要任何凭据，只要模型名在就行
            return True
        return bool(self.effective_embed_key and self.effective_embed_base)

    @property
    def embed_label(self) -> str:
        if self.embed_source == "local":
            return f"本地 · {self.embed_model}"
        return f"云端 · {self.embed_model}"

    # -- 持久化 -----------------------------------------------------------
    def save(self) -> None:
        SETTINGS_FILE.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls) -> "ModelSettings":
        if not SETTINGS_FILE.exists():
            return cls()
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        allowed = {f for f in cls.__dataclass_fields__}
        obj = cls(**{k: v for k, v in raw.items() if k in allowed})

        # 兼容旧版配置文件：那时没有 embed_source，embed_model 可能为空。
        # 直接补成本地默认模型，老用户的 Key 继续能用。
        if not obj.embed_model:
            obj.embed_source = "local"
            obj.embed_model = DEFAULT_LOCAL_EMBED
        return obj


def provider_defaults(provider: str) -> dict:
    return PROVIDERS.get(provider, PROVIDERS["自定义 (OpenAI 兼容)"])


# ---------------------------------------------------------------------------
# 对话模型（云端 OpenAI 兼容）
# ---------------------------------------------------------------------------
def build_llm(settings: ModelSettings):
    """用 OpenAILike 而不是 OpenAI。

    这一点很关键：`llama_index.llms.openai.OpenAI` 在 0.14 里会拿模型名去查
    OpenAI 官方白名单（ALL_AVAILABLE_MODELS）来推断上下文长度，遇到
    `deepseek-chat` / `qwen-plus` / `glm-4-flash` 这些非 OpenAI 模型名直接抛
    `Unknown model 'xxx'`。任何国内模型都会中招。

    `OpenAILike` 是官方为「OpenAI 兼容服务」准备的类，不做这个白名单校验，
    上下文长度由我们自己按供应商声明，所以任何兼容端点都能用。
    """
    if not settings.llm_ready:
        raise ValueError("LLM 未配置：请填写 API Key、Base URL 与模型名。")

    from llama_index.llms.openai_like import OpenAILike

    info = provider_defaults(settings.provider)
    return OpenAILike(
        model=settings.llm_model,
        api_key=settings.api_key,
        api_base=settings.base_url,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        context_window=int(info.get("context_window", 32768)),
        is_chat_model=True,
        # 我们用不到 function calling，关掉避免部分兼容服务报 400
        is_function_calling_model=False,
        timeout=120.0,
        max_retries=2,
    )


# ---------------------------------------------------------------------------
# 向量模型
# ---------------------------------------------------------------------------
_LOCAL_EMBED_CACHE: dict[str, object] = {}


def _prepare_hf_env() -> None:
    """把 HuggingFace 下载指向国内镜像。

    两个关键点（都是踩过的坑）：
    1. HF_ENDPOINT 指向 hf-mirror.com，否则国内基本下不动。
    2. 必须 HF_HUB_DISABLE_XET=1 —— 新版 huggingface_hub 默认走 Xet 存储协议，
       而 hf-mirror 不支持 Xet，会直接 401 Unauthorized。
    """
    os.environ.setdefault("HF_ENDPOINT", HF_MIRROR)
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")


def local_model_cached(model_name: str) -> bool:
    """模型是否已经下到本地目录（用来决定要不要提示"首次下载"）。"""
    if not MODEL_DIR.exists():
        return False
    short = model_name.split("/")[-1]
    return any(p.is_dir() and short in p.name for p in MODEL_DIR.iterdir())


def build_local_embed_model(model_name: str):
    """本地 embedding（fastembed + onnxruntime），进程内单例。

    必须做缓存：Streamlit 每次交互都会重跑整个脚本，不缓存的话每次都要
    重新加载 onnx 模型（1~2 秒），体验会很差。
    """
    if model_name in _LOCAL_EMBED_CACHE:
        return _LOCAL_EMBED_CACHE[model_name]

    _prepare_hf_env()
    from llama_index.embeddings.fastembed import FastEmbedEmbedding

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    _LOCAL_EMBED_CACHE[model_name] = FastEmbedEmbedding(
        model_name=model_name,
        cache_dir=str(MODEL_DIR),
        embed_batch_size=16,
    )
    return _LOCAL_EMBED_CACHE[model_name]


def build_embed_model(settings: ModelSettings):
    if not settings.embed_ready:
        raise ValueError(
            "向量模型未配置：当前用的是云端 embedding，但缺少 API Key 或 Base URL。"
            "可以在「高级设置」里切回本地模型。"
        )
    if settings.embed_source == "local":
        return build_local_embed_model(settings.embed_model)

    return OpenAIEmbedding(
        model_name=settings.embed_model,
        api_key=settings.effective_embed_key,
        api_base=settings.effective_embed_base,
        # 阿里百炼 text-embedding-v3 单次最多 10 条，取最小值保证各处都兼容。
        embed_batch_size=10,
        timeout=120.0,
        max_retries=2,
    )


def apply_global_settings(settings: ModelSettings) -> None:
    """把模型装进 LlamaIndex 的全局 Settings。

    多数组件我们都会显式传 llm/embed_model，装全局只是为了兜底
    （例如某些内部默认构造）。失败不阻塞主流程。
    """
    if settings.llm_ready:
        Settings.llm = build_llm(settings)
    if settings.embed_ready:
        Settings.embed_model = build_embed_model(settings)
    Settings.chunk_size = 256
    Settings.chunk_overlap = 32


def probe_connection(settings: ModelSettings) -> dict:
    """连通性自检：分别试 LLM 与 embedding，返回逐项结果。"""
    result: dict[str, dict] = {}

    try:
        llm = build_llm(settings)
        reply = llm.complete("回复两个字：就绪")
        result["llm"] = {"ok": True, "detail": str(reply).strip()[:60]}
    except Exception as exc:  # noqa: BLE001 - 教学工具，任何异常都应展示给用户
        result["llm"] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:300]}

    try:
        embed = build_embed_model(settings)
        vec = embed.get_text_embedding("连通性测试")
        where = "本地" if settings.embed_source == "local" else "云端"
        result["embed"] = {"ok": True, "detail": f"{where}，维度 {len(vec)}"}
    except Exception as exc:  # noqa: BLE001
        result["embed"] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"[:300]}

    return result
