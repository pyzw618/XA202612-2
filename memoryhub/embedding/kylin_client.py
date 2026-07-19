"""
Kylin Embedding 客户端 — 通过 ctypes 对接麒麟 C SDK。

在 Kylin OS 上加载 libkylin-coreai-embedding.so，
通过 DBus 与 Embedding 服务通信，获取真实语义向量。

非 Linux / 无 .so 时自动降级（is_available() → False），
工厂函数会自动回退到 MockEmbeddingClient。

SDK 调用流程（基于 kylin-coreai-embedding C API）：
  1. text_embedding_init_session_no_connect(&session)   → 创建会话
  2. text_embedding_init_model(session, model_name)      → 初始化模型
  3. text_embedding(session, text, &result)              → 调用 Embedding
  4. embedding_result_get_vector_data(result)            → 取 float* 向量
  5. embedding_result_destroy(&result)                   → 清理结果
  6. text_embedding_destroy_session(&session)            → 销毁会话

模型：ensemble-embd_gte-base_uint8-text，输出 768 维。
"""

import ctypes
import os
import platform
from typing import List, Optional

from .base import BaseEmbeddingClient

# 模型配置
DEFAULT_MODEL_NAME = "ensemble-embd_gte-base_uint8-text"
DEFAULT_DIM = 768

# .so 搜索路径（按优先级）
SO_CANDIDATES = [
    "libkylin-coreai-embedding.so",
    "libcoreai-embedding.so",
    "/usr/lib/libkylin-coreai-embedding.so",
    "/usr/local/lib/libkylin-coreai-embedding.so",
]


class KylinEmbeddingClient(BaseEmbeddingClient):
    """
    麒麟 Embedding 客户端（ctypes → .so → DBus）。

    仅在 Kylin OS + .so 存在时可用。
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        dim: int = DEFAULT_DIM,
        so_path: Optional[str] = None,
        **kwargs,  # 接受但不使用 Mock 专用参数（latency, seed 等）
    ):
        self._model_name = model_name
        self._dim = dim
        self._lib = None
        self._session = None
        self._so_path = so_path

        self._try_load()

    # ---- 公开接口 ----

    def is_available(self) -> bool:
        return self._lib is not None and self._session is not None

    def get_dimension(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        if not self.is_available():
            raise RuntimeError("KylinEmbeddingClient 不可用，请检查 .so 和环境")
        return self._call_embed(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not self.is_available():
            raise RuntimeError("KylinEmbeddingClient 不可用，请检查 .so 和环境")
        return [self._call_embed(t) for t in texts]

    # ---- 内部：.so 加载与会话初始化 ----

    def _try_load(self):
        """尝试加载 .so 并初始化会话。失败则保持 self._lib = None。"""
        if platform.system() != "Linux":
            return  # 非 Linux 不尝试

        lib = self._find_and_load_so()
        if lib is None:
            return

        try:
            session = self._init_session(lib)
            if session is not None:
                self._lib = lib
                self._session = session
        except Exception:
            pass  # 初始化失败，保持不可用状态

    def _find_and_load_so(self):
        """按候选列表搜索并加载 .so。"""
        if self._so_path:
            candidates = [self._so_path]
        else:
            candidates = SO_CANDIDATES

        for path in candidates:
            if os.path.exists(path):
                try:
                    return ctypes.CDLL(path)
                except OSError:
                    continue
        return None

    def _init_session(self, lib):
        """
        初始化 SDK 会话：创建 session → 初始化模型。
        返回 session 指针（c_void_p），失败返回 None。
        """
        # 1. 创建会话: bool text_embedding_init_session_no_connect(void** session)
        init_fn = lib.text_embedding_init_session_no_connect
        init_fn.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        init_fn.restype = ctypes.c_bool

        session = ctypes.c_void_p()
        ok = init_fn(ctypes.byref(session))
        if not ok or session.value is None:
            return None

        # 2. 初始化模型: void text_embedding_init_model(void* session, const char* model)
        init_model_fn = lib.text_embedding_init_model
        init_model_fn.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        init_model_fn.restype = None

        try:
            init_model_fn(session, self._model_name.encode("utf-8"))
        except Exception:
            return None

        return session

    # ---- 内部：Embedding 调用 ----

    def _call_embed(self, text: str) -> List[float]:
        """调用同步 Embedding API，返回 768 维向量。"""
        # 1. text_embedding(session, text, &result) → bool
        embed_fn = self._lib.text_embedding
        embed_fn.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        embed_fn.restype = ctypes.c_bool

        result = ctypes.c_void_p()
        ok = embed_fn(self._session, text.encode("utf-8"), ctypes.byref(result))
        if not ok or result.value is None:
            raise RuntimeError(f"text_embedding 调用失败: text={text[:50]}...")

        try:
            # 2. 检查错误码: int embedding_result_get_error_code(result)
            err_fn = self._lib.embedding_result_get_error_code
            err_fn.argtypes = [ctypes.c_void_p]
            err_fn.restype = ctypes.c_int

            error_code = err_fn(result)
            if error_code != 0:
                msg_fn = self._lib.embedding_result_get_error_message
                msg_fn.argtypes = [ctypes.c_void_p]
                msg_fn.restype = ctypes.c_char_p
                err_msg = msg_fn(result).decode("utf-8") if msg_fn(result) else "unknown"
                raise RuntimeError(f"Embedding 返回错误: code={error_code}, msg={err_msg}")

            # 3. 取向量长度: int embedding_result_get_vector_length(result)
            len_fn = self._lib.embedding_result_get_vector_length
            len_fn.argtypes = [ctypes.c_void_p]
            len_fn.restype = ctypes.c_int

            vec_len = len_fn(result)
            if vec_len != self._dim:
                raise RuntimeError(f"向量维度不匹配: 期望 {self._dim}，实际 {vec_len}")

            # 4. 取向量数据: float* embedding_result_get_vector_data(result)
            data_fn = self._lib.embedding_result_get_vector_data
            data_fn.argtypes = [ctypes.c_void_p]
            data_fn.restype = ctypes.POINTER(ctypes.c_float)

            vec_ptr = data_fn(result)
            vector = [vec_ptr[i] for i in range(vec_len)]

            return vector

        finally:
            # 5. 清理结果: void embedding_result_destroy(void** result)
            destroy_fn = self._lib.embedding_result_destroy
            destroy_fn.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
            destroy_fn.restype = None
            destroy_fn(ctypes.byref(result))

    def __del__(self):
        """销毁会话。"""
        if getattr(self, "_lib", None) is not None and getattr(self, "_session", None) is not None:
            try:
                destroy_fn = self._lib.text_embedding_destroy_session
                destroy_fn.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
                destroy_fn.restype = None
                destroy_fn(ctypes.byref(self._session))
            except Exception:
                pass
