"""全局配置管理"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StorageConfig:
    """存储相关配置"""
    db_path: str = "data/memoryhub.db"
    vector_index_path: str = "data/vector_index"
    evidence_path: str = "data/evidence"
    cache_max_size: int = 1000


@dataclass
class RetrievalConfig:
    """检索相关配置"""
    default_top_k: int = 5
    vector_weight: float = 0.6
    keyword_weight: float = 0.3
    metadata_weight: float = 0.1
    rerank_enabled: bool = True
    cache_ttl_seconds: int = 300


@dataclass
class LLMConfig:
    """LLM 调用配置"""
    provider: str = "openai"  # "openai" | "ollama"
    api_base: str = "http://localhost:11434/v1"
    api_key: str = ""
    model: str = "qwen2:1.5b"
    temperature: float = 0.1
    max_tokens: int = 2048


@dataclass
class EmbeddingConfig:
    """Embedding 配置"""
    provider: str = "mock"  # "kylin" | "mock"
    dimension: int = 1024
    model_name: str = ""


@dataclass
class SafetyConfig:
    """安全过滤配置"""
    sensitive_patterns: list[str] = field(default_factory=lambda: [
        r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S+",
        r"\b\d{18}\b",  # 身份证号
        r"\b1[3-9]\d{9}\b",  # 手机号
    ])
    auto_mask: bool = True
    reject_on_detect: bool = False


@dataclass
class AppConfig:
    """应用总配置"""
    storage: StorageConfig = field(default_factory=StorageConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    debug: bool = False


def load_config() -> AppConfig:
    """加载配置，优先从环境变量/配置文件读取"""
    return AppConfig()
