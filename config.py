"""全局配置：供应商预设、切片策略元数据、检索模块元数据。

设计原则：所有"教学解释"文本集中在这里，界面层只负责渲染，
这样调整文案不需要动业务逻辑。
"""

from __future__ import annotations

from pathlib import Path

APP_TITLE = "RAG 知识库教学教具"
APP_SUBTITLE = "LlamaIndex · 切片策略 × 可插拔检索模块"

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SAMPLE_DIR = DATA_DIR / "samples"
STORAGE_DIR = DATA_DIR / "storage"
UPLOAD_DIR = DATA_DIR / "uploads"
SETTINGS_FILE = DATA_DIR / "settings.json"

for _d in (DATA_DIR, SAMPLE_DIR, STORAGE_DIR, UPLOAD_DIR):
    _d.mkdir(parents=True, exist_ok=True)

MODEL_DIR = DATA_DIR / "models" / "fastembed"


# ---------------------------------------------------------------------------
# 1. 模型供应商预设：选中后自动填 base_url / 默认模型，用户只需填 API Key
# ---------------------------------------------------------------------------
# 说明：embed_model 为 None 表示该供应商不提供 embedding 接口，
# 此时向量检索不可用，需要另选一家做嵌入（界面会提示）。
PROVIDERS: dict[str, dict] = {
    "硅基流动 SiliconFlow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "llm_models": ["Qwen/Qwen2.5-7B-Instruct", "Qwen/Qwen2.5-32B-Instruct", "deepseek-ai/DeepSeek-V2.5"],
        "embed_models": ["BAAI/bge-m3", "BAAI/bge-large-zh-v1.5", "netease-youdao/bce-embedding-base_v1"],
        "context_window": 32768,
        "signup": "https://cloud.siliconflow.cn/",
    },
    "阿里百炼 DashScope": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "llm_models": ["qwen-plus", "qwen-turbo", "qwen-max"],
        "embed_models": ["text-embedding-v3", "text-embedding-v2"],
        "context_window": 131072,
        "signup": "https://bailian.console.aliyun.com/",
    },
    "智谱 BigModel": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "llm_models": ["glm-4-flash", "glm-4-air", "glm-4-plus"],
        "embed_models": ["embedding-3"],
        "context_window": 131072,
        "signup": "https://open.bigmodel.cn/",
    },
    "DeepSeek": {
        "base_url": "https://api.deepseek.com/v1",
        "llm_models": ["deepseek-chat", "deepseek-reasoner"],
        "embed_models": [],  # 不提供 embedding
        "context_window": 65536,
        "signup": "https://platform.deepseek.com/",
    },
    "月之暗面 Moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "llm_models": ["moonshot-v1-8k", "moonshot-v1-32k"],
        "embed_models": [],  # 不提供 embedding
        "context_window": 8192,
        "signup": "https://platform.moonshot.cn/",
    },
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "llm_models": ["gpt-4o-mini", "gpt-4o"],
        "embed_models": ["text-embedding-3-small", "text-embedding-3-large"],
        "context_window": 128000,
        "signup": "https://platform.openai.com/",
    },
    "自定义 (OpenAI 兼容)": {
        "base_url": "",
        "llm_models": [],
        "embed_models": [],
        "context_window": 32768,
        "signup": "",
    },
}

DEFAULT_PROVIDER = "硅基流动 SiliconFlow"


# ---------------------------------------------------------------------------
# 1.5 本地 Embedding：不需要第二个 API Key
# ---------------------------------------------------------------------------
# 对话模型走云端（你填的那个 Key），向量模型在本机跑。
# 模型文件通过 HF 镜像（hf-mirror.com）下载，一次下完永久离线可用。
HF_MIRROR = "https://hf-mirror.com"

LOCAL_EMBED_MODELS: dict[str, dict] = {
    "BAAI/bge-small-zh-v1.5": {
        "dim": 512,
        "size": "约 90MB",
        "desc": "中文小模型，默认档。速度最快，教学和中小知识库完全够用。",
    },
    "jinaai/jina-embeddings-v2-base-zh": {
        "dim": 768,
        "size": "约 640MB",
        "desc": "中文长文本模型，支持 8K 上下文。块切得很大时更合适，但更慢更占内存。",
    },
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": {
        "dim": 384,
        "size": "约 220MB",
        "desc": "多语言模型，中英混排文档表现更均衡。",
    },
}

DEFAULT_LOCAL_EMBED = "BAAI/bge-small-zh-v1.5"

EMBED_SOURCES = {
    "local": "本地模型（不需要 Key，首次自动下载）",
    "api": "云端 API（用同一个 Key，或单独配一家）",
}


# ---------------------------------------------------------------------------
# 2. 切片策略：五种，每种都绑定"最适合什么形状的文档"和"为什么"
# ---------------------------------------------------------------------------
CHUNK_STRATEGIES: dict[str, dict] = {
    "token": {
        "label": "① Token 切片（固定窗口）",
        "short": "Token 切片",
        "samples": [
            "10_二级学院与专业详解.txt",
            "01_新生入学指南.txt",
        ],
        "sample_why": "608 行 / 26KB，全库最长的连续正文，13 个学院逐个罗列 —— 最容易被固定窗口从中间切断。",
        "node_parser": "TokenTextSplitter",
        "fits": "版式平坦的长篇连续文本：政策白皮书、招股书、论文正文。没有小标题可用，只能按字数硬切。",
        "why": "按固定的 token 数开窗，窗口之间保留重叠，保证跨窗口的句子不会被切断丢失。速度最快、成本最低，是绝大多数系统的默认档。",
        "risk": "会把一句话、一个完整论述从中间切断；对文档的语义边界完全不敏感。",
        "params": {"chunk_size": 256, "chunk_overlap": 32},
    },
    "sentence": {
        "label": "② 句子切片（一句一节点）",
        "short": "句子切片",
        "samples": [
            "08_高频问答FAQ.txt",
            "09_数字与时间表.txt",
        ],
        "sample_why": "50 组一问一答 + 84 行数字表，每条自足不依赖上下文 —— 一句一节点的理想输入。",
        "node_parser": "SentenceNodeParser（LlamaIndex NodeParser 子类）",
        "fits": "本身就是短句条目的文档：FAQ、术语表、参数表、规章条款。每条信息自足，不依赖上下文。",
        "why": "每个句子独立成一个节点，粒度最细。命中时不会有任何无关信息混进来，答案干净、上下文成本最低。",
        "risk": "句子一旦有指代（「它」「该措施」「上面的方案」）就会失去主语，检索到也用不了。对长句会切得过碎。",
        "params": {},
    },
    "sentence_window": {
        "label": "③ 句子窗口切片（句子 + 前后文）",
        "short": "句子窗口",
        "samples": [
            "02_教学与学习指南.txt",
            "06_运动活动与学业管理指南.txt",
            "07_校园布局与生活细则指南.txt",
        ],
        "sample_why": "选课 / 转专业 / 考勤 / 宿舍细则这类规章，条款之间互相引用（「上述情况」「该生」）—— 单句抽出来会缺主语。",
        "node_parser": "SentenceWindowNodeParser(window_size=N)",
        "fits": "句子之间存在强依赖的文档：客服对话、会议记录、运维日志、带大量指代的叙述。",
        "why": "用句子做检索单元（精准），但节点里存下前后 N 句（完整）。检索命中后再把窗口文本换回去，兼顾「找得准」和「读得懂」。",
        "risk": "索引体积变大（每个节点存一份窗口）；窗口开太大等于回到暴力切片，开太小救不回指代。",
        "params": {"window_size": 3},
    },
    "semantic": {
        "label": "④ 语义切片（按主题转折切）",
        "short": "语义切片",
        "samples": [
            "03_生活与日常指南.txt",
            "05_安全医疗与心理健康指南.txt",
        ],
        "sample_why": "食堂 → 超市 → 快递 → 水电、安全 → 校医院 → 医保 → 心理：主题一路跳转，正好让语义切块「一个块一个主题」。",
        "node_parser": "SemanticSplitterNodeParser",
        "fits": "主题频繁转折但没有任何标题的文档：会议纪要、综述、长篇访谈、拼贴式笔记。",
        "why": "逐句算 embedding，相邻句子向量距离突然变大的地方就是主题转折点，在那里下刀。切出来的块天然「一个块一个主题」。",
        "risk": "建索引时要为每一句调用 embedding 接口，最慢也最贵；阈值调不好会切得过碎或切不开。",
        "params": {"buffer_size": 1, "breakpoint_percentile_threshold": 95},
    },
    "markdown": {
        "label": "⑤ Markdown 切片（按标题层级）",
        "short": "Markdown 切片",
        "samples": [
            "10_二级学院与专业详解.txt",
            "04_奖助学金社团与就业指南.txt",
            "11_收费标准与中外合作项目.txt",
        ],
        "sample_why": "## 学院 → ### 学院概况 / 本科专业 / 专科专业 / 排名荣誉，102 个标题层级最深 —— 文档结构就是检索结构。",
        "node_parser": "MarkdownNodeParser",
        "fits": "作者已经帮你分好段的文档：Markdown 手册、API 文档、Wiki、带标题的规范。",
        "why": "直接用 #/##/### 的层级当切分边界，文档结构就是检索结构。切出来的块自带标题路径，天生可解释。",
        "risk": "对没有标题的纯文本完全失效（退化成整块）；标题层级写得乱，切出来也会乱。",
        "params": {},
    },
}

DEFAULT_STRATEGY = "token"


# ---------------------------------------------------------------------------
# 3. 检索模块：四个可插拔开关
# ---------------------------------------------------------------------------
MODULE_INFO: dict[str, dict] = {
    "vector": {
        "label": "向量检索（Dense）",
        "desc": "把问题和文本块都编码成向量，按余弦相似度召回。**唯一能理解同义改写的通道**——问「充电充不进去」，也能召回写「充不进电」的段落。",
        "off_effect": "关掉后完全失去语义匹配能力，只能靠字面重合。",
    },
    "bm25": {
        "label": "BM25 关键词检索（Sparse）",
        "desc": "经典词频算法：词在本文档出现得多、在全局出现得少，就更能代表这篇文档。**对专有名词、型号、错误码、数字极其敏感**。",
        "off_effect": "关掉后「XHC-100A」「42902」「9.9 元」这类精确 token 只能靠向量碰运气。",
    },
    "hybrid": {
        "label": "混合检索（RRF 融合）",
        "desc": "向量和 BM25 各召回一批，再用 Reciprocal Rank Fusion 按**排名**而非分数融合。两路互补，是生产环境的默认答案。",
        "off_effect": "关掉后只能单通道召回，一条路漏了就彻底漏了。",
    },
    "rerank": {
        "label": "Rerank 重排",
        "desc": "检索只负责「从海量里捞出候选」，Rerank 负责「从候选里精挑细选」。用 LLM 逐个判断候选块与问题的真实相关性后重排，**代价是多一次模型调用**。",
        "off_effect": "关掉后最终上下文完全由召回的相似度分数决定，容易把「字面像但没用」的块塞进 prompt。",
    },
}

DEFAULT_MODULES = {
    "vector": True,
    "bm25": True,
    "hybrid": True,
    "rerank": True,
}


def sample_path(filename: str) -> Path:
    return SAMPLE_DIR / filename
