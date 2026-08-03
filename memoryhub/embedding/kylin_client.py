"""
Kylin Embedding 客户端 — 通过 ctypes 对接麒麟 C SDK。

在 Kylin OS 上加载 libkylin-coreai-embedding.so，
通过 DBus 与 Embedding 服务通信，获取真实语义向量。

非 Linux / 无 .so 时自动降级（is_available() → False），
工厂函数会自动回退到 MockEmbeddingClient。

use_mock=True 时加载项目内 mock 动态库（libkylin-coreai-embedding-mock，
与真实 SDK 导出相同符号，可在 Windows/Linux 开发机上跑通 ctypes 链路）。

SDK 调用流程（基于 kylin-coreai-embedding C API 公开头文件，
见 docs/retrieval/2026-08-02_kylin_embedding_sdk_api_signatures.md）：
  1. text_embedding_create_session()                     → 创建会话
  2. text_embedding_init_session(session)                → 连接后端
  3. text_embedding_init_model(session, model_name)      → 初始化模型
  4. text_embedding(session, text, &result)              → 调用 Embedding
  5. embedding_result_get_vector_data(result)            → 取 float* 向量
  6. embedding_result_destroy(&result)                   → 清理结果
  7. text_embedding_destroy_session(&session)            → 销毁会话

模型：ensemble-embd_gte-base_uint8-text，输出 768 维。
"""

import ctypes
import os
import platform
import sys
from pathlib import Path
from typing import List, Optional

from .base import BaseEmbeddingClient

# 模型配置
DEFAULT_MODEL_NAME = "ensemble-embd_gte-base_uint8-text"
DEFAULT_DIM = 768

# mock 动态库固定输出 768 维（见 third_party/kylin-mock/embedding_mock.c）
MOCK_DIM = 768

# .so 搜索路径（按优先级）
SO_CANDIDATES = [
    "libkylin-coreai-embedding.so",
    "libcoreai-embedding.so",
    "/usr/lib/libkylin-coreai-embedding.so",
    "/usr/local/lib/libkylin-coreai-embedding.so",
]

# 项目内 mock 动态库目录（项目根/third_party/kylin-mock/build/）
_MOCK_LIB_DIR = (
    Path(__file__).resolve().parents[2] / "third_party" / "kylin-mock" / "build"
)

_MOCK_LIB_NAMES = {
    "win32": "libkylin-coreai-embedding-mock.dll",
    "linux": "libkylin-coreai-embedding-mock.so",
    "darwin": "libkylin-coreai-embedding-mock.dylib",
}


def _platform_key() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    return "win32"


class KylinEmbeddingError(RuntimeError):
    """不携带输入文本或后端错误消息的稳定 Embedding 错误。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class KylinEmbeddingClient(BaseEmbeddingClient):
    """
    麒麟 Embedding 客户端（ctypes → .so → DBus）。

    仅在 Kylin OS + .so 存在时可用；use_mock=True 时改用项目内
    mock 动态库，可在非麒麟环境跑通完整 ctypes 调用链路。
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        dim: int = DEFAULT_DIM,
        so_path: Optional[str] = None,
        use_mock: bool = False,
        mock_so_path: Optional[str] = None,
        **kwargs,  # 接受但不使用 Mock 专用参数（latency, seed 等）
    ):
        """
        参数:
            model_name: 模型名称（真实 SDK 模式）
            dim: 向量维度；mock 模式固定为 768，传入值会被忽略
            so_path: 真实 .so 显式路径（优先于候选列表）
            use_mock: 是否使用项目内 mock 动态库
            mock_so_path: mock 动态库显式路径，缺省指向
                third_party/kylin-mock/build/
        """
        self._model_name = model_name
        self._use_mock = use_mock
        # mock 动态库只提供 768 维模型，维度以库的实际输出为准
        self._dim = MOCK_DIM if use_mock else dim
        self._lib = None
        self._session = None
        self._so_path = mock_so_path if use_mock else so_path

        self._try_load()

    # ---- 公开接口 ----

    def is_available(self) -> bool:
        return self._lib is not None and self._session is not None

    def get_dimension(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        if not self.is_available():
            raise KylinEmbeddingError("embedding.unavailable")
        return self._call_embed(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not self.is_available():
            raise KylinEmbeddingError("embedding.unavailable")
        return [self._call_embed(t) for t in texts]

    # ---- 内部：.so 加载与会话初始化 ----

    def _try_load(self):
        """尝试加载 .so 并初始化会话。失败则保持 self._lib = None。"""
        if not self._use_mock and platform.system() != "Linux":
            return  # 真实 SDK 仅在 Linux 上尝试；mock 库不限平台

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
        """按候选列表搜索并加载动态库。"""
        if self._so_path:
            candidates = [self._so_path]
        elif self._use_mock:
            candidates = [str(_MOCK_LIB_DIR / _MOCK_LIB_NAMES[_platform_key()])]
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
        初始化 SDK 会话：创建 session → 连接后端 → 初始化模型。
        返回 session 指针（c_void_p），失败返回 None。

        注意：公开头文件不存在 text_embedding_init_session_no_connect()，
        正确流程是 create_session() + init_session()（见签名文档 2.1/2.2）。
        """
        # 1. 创建会话: TextEmbeddingSession* text_embedding_create_session(void)
        create_fn = lib.text_embedding_create_session
        create_fn.argtypes = []
        create_fn.restype = ctypes.c_void_p

        session = ctypes.c_void_p(create_fn())
        if session.value is None:
            return None

        # 2. 连接后端: int text_embedding_init_session(TextEmbeddingSession*)
        init_fn = lib.text_embedding_init_session
        init_fn.argtypes = [ctypes.c_void_p]
        init_fn.restype = ctypes.c_int

        if init_fn(session) != 0:
            self._destroy_session(lib, session)
            return None

        # 3. 初始化模型: int text_embedding_init_model(session, const char* model)
        init_model_fn = lib.text_embedding_init_model
        init_model_fn.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        init_model_fn.restype = ctypes.c_int

        try:
            rc = init_model_fn(session, self._model_name.encode("utf-8"))
        except Exception:
            rc = -1
        if rc != 0:
            self._destroy_session(lib, session)
            return None

        return session

    @staticmethod
    def _destroy_session(lib, session) -> None:
        """销毁会话（尽力而为，不抛异常）。"""
        try:
            destroy_fn = lib.text_embedding_destroy_session
            destroy_fn.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
            destroy_fn.restype = None
            destroy_fn(ctypes.byref(session))
        except Exception:
            pass

    # ---- 内部：Embedding 调用 ----

    def _call_embed(self, text: str) -> List[float]:
        """调用同步 Embedding API，返回稠密向量。"""
        lib = self._lib
        session = self._session
        if lib is None or session is None:
            raise KylinEmbeddingError("embedding.unavailable")

        # 1. text_embedding(session, text, &result) → bool
        symbol_error = False
        try:
            embed_fn = lib.text_embedding
            embed_fn.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            embed_fn.restype = ctypes.c_bool
        except Exception:
            symbol_error = True
        if symbol_error:
            raise KylinEmbeddingError("embedding.backend_error") from None

        result = ctypes.c_void_p()
        encoding_error = False
        try:
            encoded_text = text.encode("utf-8")
        except UnicodeError:
            encoding_error = True
            encoded_text = b""
        if encoding_error:
            raise KylinEmbeddingError("embedding.invalid_text") from None
        call_error = False
        try:
            ok = embed_fn(session, encoded_text, ctypes.byref(result))
        except Exception:
            call_error = True
            ok = False
        if call_error:
            raise KylinEmbeddingError("embedding.call_failed") from None
        if not ok or result.value is None:
            raise KylinEmbeddingError("embedding.call_failed")

        vector: List[float] | None = None
        backend_error = False
        try:
            # 2. 检查错误码: int embedding_result_get_error_code(result)
            err_fn = lib.embedding_result_get_error_code
            err_fn.argtypes = [ctypes.c_void_p]
            err_fn.restype = ctypes.c_int

            error_code = err_fn(result)
            if error_code != 0:
                # 错误信息可能含输入文本，只暴露稳定错误码
                raise KylinEmbeddingError("embedding.sdk_error")

            # 3. 取向量长度: int embedding_result_get_vector_length(result)
            len_fn = lib.embedding_result_get_vector_length
            len_fn.argtypes = [ctypes.c_void_p]
            len_fn.restype = ctypes.c_int

            vec_len = len_fn(result)
            if vec_len != self._dim:
                raise KylinEmbeddingError("embedding.dimension_mismatch")

            # 4. 取向量数据: float* embedding_result_get_vector_data(result)
            data_fn = lib.embedding_result_get_vector_data
            data_fn.argtypes = [ctypes.c_void_p]
            data_fn.restype = ctypes.POINTER(ctypes.c_float)

            vec_ptr = data_fn(result)
            vector = [vec_ptr[i] for i in range(vec_len)]

        except KylinEmbeddingError:
            raise
        except Exception:
            backend_error = True
        finally:
            # 5. 清理结果: void embedding_result_destroy(void** result)
            try:
                destroy_fn = lib.embedding_result_destroy
                destroy_fn.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
                destroy_fn.restype = None
                destroy_fn(ctypes.byref(result))
            except Exception:
                pass
        if backend_error or vector is None:
            raise KylinEmbeddingError("embedding.backend_error") from None
        return vector

    def __del__(self):
        """销毁会话。"""
        if (
            getattr(self, "_lib", None) is not None
            and getattr(self, "_session", None) is not None
        ):
            self._destroy_session(self._lib, self._session)
