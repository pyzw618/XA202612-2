"""
Milvus 向量引擎 C API 的 ctypes 桥接。

按 docs/2026-08-02_milvus_c_api_minimal_interface.md 绑定全部导出函数，
封装句柄管理、错误检查和 out_json 缓冲区释放。仅供
milvus_engine.MilvusVectorEngine 内部使用。
"""

import ctypes
import sys
from ctypes import (
    POINTER,
    CDLL,
    byref,
    c_char_p,
    c_float,
    c_int,
    c_uint32,
    c_void_p,
)
from pathlib import Path
from typing import Optional

# 不透明引擎句柄
vector_engine_t = c_void_p

# 项目内 mock 动态库相对路径（项目根/third_party/kylin-mock/build/）
_MOCK_LIB_DIR = Path(__file__).resolve().parents[3] / "third_party" / "kylin-mock" / "build"

_MOCK_LIB_NAMES = {
    "win32": "libkysdk-vector-engine-client-capi-mock.dll",
    "linux": "libkysdk-vector-engine-client-capi-mock.so",
    "darwin": "libkysdk-vector-engine-client-capi-mock.dylib",
}

_REAL_LIB_NAMES = {
    "win32": "libkysdk-vector-engine-client-capi.dll",
    "linux": "libkysdk-vector-engine-client-capi.so",
    "darwin": "libkysdk-vector-engine-client-capi.dylib",
}

# 真实库的常见安装路径
_DEFAULT_SEARCH_DIRS = [
    "/usr/lib",
    "/usr/local/lib",
    "/usr/lib64",
    "/usr/local/lib64",
]


class MilvusEngineError(RuntimeError):
    """向量引擎 C API 调用失败。异常信息只含错误文本，不含用户数据。"""


def _platform_key() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    return "win32"


def _probe_library_path(so_path: Optional[str], mock: bool) -> str:
    """
    确定要加载的动态库路径。

    优先级：显式 so_path > mock 模式下项目内 mock 库 > 平台默认安装路径。
    """
    platform = _platform_key()

    if so_path:
        path = Path(so_path)
        if not path.exists():
            raise MilvusEngineError(f"向量引擎动态库不存在: {so_path}")
        return str(path)

    if mock:
        path = _MOCK_LIB_DIR / _MOCK_LIB_NAMES[platform]
        if not path.exists():
            raise MilvusEngineError(
                f"mock 动态库不存在: {path}，请先编译 third_party/kylin-mock"
            )
        return str(path)

    lib_name = _REAL_LIB_NAMES[platform]
    for directory in _DEFAULT_SEARCH_DIRS:
        path = Path(directory) / lib_name
        if path.exists():
            return str(path)
    raise MilvusEngineError(
        f"未找到向量引擎动态库 {lib_name}，请通过 so_path 显式指定"
    )


class _MilvusCAPI:
    """
    libkysdk-vector-engine-client-capi 的 ctypes 封装。

    负责：函数签名绑定、返回码检查（非零时抛 MilvusEngineError）、
    out_json 缓冲区取值与释放（try/finally 保证释放）、文本 UTF-8 编码。
    """

    def __init__(self, so_path: Optional[str] = None, mock: bool = False):
        lib_path = _probe_library_path(so_path, mock)
        try:
            self._lib = CDLL(lib_path)
        except OSError as exc:
            raise MilvusEngineError(f"加载向量引擎动态库失败: {exc}") from exc
        self._bind()

    # ---- 函数签名绑定 ----

    def _bind(self) -> None:
        lib = self._lib

        lib.vector_engine_create.restype = vector_engine_t
        lib.vector_engine_create.argtypes = []

        lib.vector_engine_connect.restype = c_int
        lib.vector_engine_connect.argtypes = [vector_engine_t, c_char_p, c_int]

        lib.vector_engine_disconnect.restype = c_int
        lib.vector_engine_disconnect.argtypes = [vector_engine_t]

        lib.vector_engine_destroy.restype = None
        lib.vector_engine_destroy.argtypes = [vector_engine_t]

        lib.vector_engine_create_collection.restype = c_int
        lib.vector_engine_create_collection.argtypes = [vector_engine_t, c_char_p, c_int]

        lib.vector_engine_load_collection.restype = c_int
        lib.vector_engine_load_collection.argtypes = [vector_engine_t, c_char_p]

        lib.vector_engine_release_collection.restype = c_int
        lib.vector_engine_release_collection.argtypes = [vector_engine_t, c_char_p]

        lib.vector_engine_drop_collection.restype = c_int
        lib.vector_engine_drop_collection.argtypes = [vector_engine_t, c_char_p]

        lib.vector_engine_insert.restype = c_int
        lib.vector_engine_insert.argtypes = [
            vector_engine_t, c_char_p, c_char_p, c_char_p,
            POINTER(c_float), c_int,
        ]

        lib.vector_engine_delete.restype = c_int
        lib.vector_engine_delete.argtypes = [vector_engine_t, c_char_p, c_char_p]

        lib.vector_engine_hybrid_search.restype = c_int
        lib.vector_engine_hybrid_search.argtypes = [
            vector_engine_t, c_char_p,
            POINTER(c_float), c_int,
            POINTER(c_uint32), POINTER(c_float), c_int,
            c_int, POINTER(c_char_p),
        ]

        lib.vector_engine_dense_search.restype = c_int
        lib.vector_engine_dense_search.argtypes = [
            vector_engine_t, c_char_p,
            POINTER(c_float), c_int,
            c_int, POINTER(c_char_p),
        ]

        lib.vector_engine_sparse_search.restype = c_int
        lib.vector_engine_sparse_search.argtypes = [
            vector_engine_t, c_char_p,
            POINTER(c_uint32), POINTER(c_float), c_int,
            c_int, POINTER(c_char_p),
        ]

        lib.vector_engine_free_buffer.restype = None
        lib.vector_engine_free_buffer.argtypes = [c_void_p]

        lib.vector_engine_get_last_error.restype = c_int
        lib.vector_engine_get_last_error.argtypes = [vector_engine_t, POINTER(c_char_p)]

    # ---- 生命周期 ----

    def create(self) -> vector_engine_t:
        """创建引擎句柄，失败抛 MilvusEngineError。"""
        handle = self._lib.vector_engine_create()
        if not handle:
            raise MilvusEngineError("创建向量引擎实例失败")
        return handle

    def connect(self, handle: vector_engine_t, host: str, port: int) -> None:
        rc = self._lib.vector_engine_connect(handle, host.encode("utf-8"), port)
        self._check_rc(handle, rc, "connect")

    def disconnect(self, handle: vector_engine_t) -> None:
        rc = self._lib.vector_engine_disconnect(handle)
        self._check_rc(handle, rc, "disconnect")

    def destroy(self, handle: vector_engine_t) -> None:
        self._lib.vector_engine_destroy(handle)

    # ---- Collection 管理 ----

    def create_collection(self, handle: vector_engine_t, name: str, dim: int) -> None:
        rc = self._lib.vector_engine_create_collection(handle, name.encode("utf-8"), dim)
        self._check_rc(handle, rc, "create_collection")

    def load_collection(self, handle: vector_engine_t, name: str) -> None:
        rc = self._lib.vector_engine_load_collection(handle, name.encode("utf-8"))
        self._check_rc(handle, rc, "load_collection")

    def release_collection(self, handle: vector_engine_t, name: str) -> None:
        rc = self._lib.vector_engine_release_collection(handle, name.encode("utf-8"))
        self._check_rc(handle, rc, "release_collection")

    def drop_collection(self, handle: vector_engine_t, name: str) -> None:
        rc = self._lib.vector_engine_drop_collection(handle, name.encode("utf-8"))
        self._check_rc(handle, rc, "drop_collection")

    # ---- 数据操作 ----

    def insert(
        self,
        handle: vector_engine_t,
        collection: str,
        memory_id: str,
        content: str,
        dense_vector: list[float],
    ) -> None:
        dim = len(dense_vector)
        vec_arr = (c_float * dim)(*dense_vector)
        rc = self._lib.vector_engine_insert(
            handle,
            collection.encode("utf-8"),
            memory_id.encode("utf-8"),
            content.encode("utf-8"),
            vec_arr,
            dim,
        )
        self._check_rc(handle, rc, "insert")

    def delete(self, handle: vector_engine_t, collection: str, memory_id: str) -> None:
        rc = self._lib.vector_engine_delete(
            handle, collection.encode("utf-8"), memory_id.encode("utf-8")
        )
        self._check_rc(handle, rc, "delete")

    # ---- 检索（返回 JSON 字符串） ----

    def hybrid_search(
        self,
        handle: vector_engine_t,
        collection: str,
        dense_vector: list[float],
        sparse_terms: list[tuple[int, float]],
        top_k: int,
    ) -> str:
        dim = len(dense_vector)
        vec_arr = (c_float * dim)(*dense_vector)
        idx_arr, val_arr, count = self._sparse_arrays(sparse_terms)
        out_json = c_char_p()
        try:
            rc = self._lib.vector_engine_hybrid_search(
                handle, collection.encode("utf-8"),
                vec_arr, dim,
                idx_arr, val_arr, count,
                top_k, byref(out_json),
            )
            self._check_rc(handle, rc, "hybrid_search")
            return self._take_json(out_json)
        finally:
            self._free_out_json(out_json)

    def dense_search(
        self,
        handle: vector_engine_t,
        collection: str,
        dense_vector: list[float],
        top_k: int,
    ) -> str:
        dim = len(dense_vector)
        vec_arr = (c_float * dim)(*dense_vector)
        out_json = c_char_p()
        try:
            rc = self._lib.vector_engine_dense_search(
                handle, collection.encode("utf-8"),
                vec_arr, dim,
                top_k, byref(out_json),
            )
            self._check_rc(handle, rc, "dense_search")
            return self._take_json(out_json)
        finally:
            self._free_out_json(out_json)

    def sparse_search(
        self,
        handle: vector_engine_t,
        collection: str,
        sparse_terms: list[tuple[int, float]],
        top_k: int,
    ) -> str:
        idx_arr, val_arr, count = self._sparse_arrays(sparse_terms)
        out_json = c_char_p()
        try:
            rc = self._lib.vector_engine_sparse_search(
                handle, collection.encode("utf-8"),
                idx_arr, val_arr, count,
                top_k, byref(out_json),
            )
            self._check_rc(handle, rc, "sparse_search")
            return self._take_json(out_json)
        finally:
            self._free_out_json(out_json)

    # ---- 内部工具 ----

    @staticmethod
    def _sparse_arrays(sparse_terms: list[tuple[int, float]]):
        """把 [(index, weight), ...] 转换为 C 数组。"""
        count = len(sparse_terms)
        if count == 0:
            return None, None, 0
        idx_arr = (c_uint32 * count)(*(index for index, _ in sparse_terms))
        val_arr = (c_float * count)(*(weight for _, weight in sparse_terms))
        return idx_arr, val_arr, count

    @staticmethod
    def _take_json(out_json: c_char_p) -> str:
        """从 out 参数取 UTF-8 字符串（不负责释放）。"""
        if not out_json.value:
            return ""
        return out_json.value.decode("utf-8")

    def _free_out_json(self, out_json: c_char_p) -> None:
        """释放 C 侧分配的 out_json 缓冲区。"""
        if out_json.value:
            self._lib.vector_engine_free_buffer(out_json)

    def _check_rc(self, handle: vector_engine_t, rc: int, operation: str) -> None:
        """返回码非零时取 last_error 并抛 MilvusEngineError。"""
        if rc == 0:
            return
        message = self._get_last_error(handle)
        detail = f"（{message}）" if message else ""
        raise MilvusEngineError(f"向量引擎 {operation} 失败，返回码 {rc}{detail}")

    def _get_last_error(self, handle: vector_engine_t) -> str:
        """获取最后一次错误描述，缓冲区取值后释放。"""
        out_message = c_char_p()
        try:
            rc = self._lib.vector_engine_get_last_error(handle, byref(out_message))
            if rc != 0 or not out_message.value:
                return ""
            return out_message.value.decode("utf-8", errors="replace")
        finally:
            if out_message.value:
                self._lib.vector_engine_free_buffer(out_message)
