"""
银河麒麟 Embedding SDK 封装

通过 Python ctypes/cffi 调用麒麟 SDK 的 C 接口，
底层通过 D-Bus 调用本地 embedding 服务。
"""

from memoryhub.embedding.base import BaseEmbeddingClient


class KylinEmbeddingClient(BaseEmbeddingClient):
    """
    麒麟 Embedding SDK 客户端

    使用方式:
        client = KylinEmbeddingClient()
        client.init_session()
        vector = client.embed("项目周报生成流程")

    SDK 接口映射:
        C API                          → Python 方法
        ─────────────────────────────────────────────
        text_embedding_create_session  → init_session
        text_embedding_init_model      → load_model
        text_embedding                 → embed
        text_embedding_async           → embed_async
        text_embedding_destroy_session → close
    """

    def __init__(self, model_name: str = ""):
        """
        参数:
            model_name: 模型名称（为空时自动获取默认模型）
        """
        self.model_name = model_name
        self._session = None
        self._lib = None
        self._dimension = 1024

    def init_session(self) -> None:
        """
        初始化 embedding session

        数据流:
            加载 .so 动态库
            → text_embedding_create_session
            → text_embedding_init_session
            → text_embedding_init_model

        异常:
            RuntimeError: 初始化失败时抛出
        """
        raise NotImplementedError

    def load_model(self, model_name: str) -> None:
        """
        加载指定模型

        参数:
            model_name: 模型名称，可通过 get_model_list 获取
        """
        raise NotImplementedError

    def get_model_list(self) -> list[dict]:
        """
        获取可用模型列表

        返回:
            [{"name": "...", "dimension": 1024, ...}, ...]
        """
        raise NotImplementedError

    def embed(self, text: str) -> list[float]:
        """
        文本向量化（同步）

        数据流:
            text → text_embedding → 获取 float* → 转为 Python list

        参数:
            text: 待向量化的文本

        返回:
            float 列表

        实现说明:
            调用 C 接口 text_embedding(session, text, &result)
            然后通过 embedding_result_get_vector_data 获取 float*
            通过 embedding_result_get_vector_length 获取长度
            最后调用 embedding_result_destroy 释放资源
        """
        raise NotImplementedError

    def embed_async(self, text: str, callback=None) -> None:
        """
        文本向量化（异步）

        参数:
            text: 待向量化的文本
            callback: 回调函数，签名 (vector: list[float]) -> None
        """
        raise NotImplementedError

    def batch_embed(self, texts: list[str]) -> list[list[float]]:
        """
        批量向量化

        实现: 逐条调用 embed（SDK 无原生批量接口）
        """
        raise NotImplementedError

    def get_dimension(self) -> int:
        """返回向量维度"""
        return self._dimension

    def is_available(self) -> bool:
        """检查 SDK 和 D-Bus 服务是否可用"""
        raise NotImplementedError

    def close(self) -> None:
        """
        释放 session 资源

        调用 text_embedding_destroy_session
        """
        raise NotImplementedError

    def _load_library(self) -> None:
        """
        加载麒麟 SDK 动态库

        实现: ctypes.CDLL("libkylin-coreai-embedding.so")
        """
        raise NotImplementedError
