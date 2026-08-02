#!/usr/bin/env python3
"""Verify the kylin-mock shared libraries load and behave correctly via ctypes.

Run after build_mock.py:
    D:/project/XA202612-2/.venv/Scripts/python.exe third_party/kylin-mock/verify_mock.py
"""

import ctypes
import json
import math
import os
import sys
from ctypes import (
    POINTER,
    byref,
    c_bool,
    c_char_p,
    c_float,
    c_int,
    c_uint32,
    c_void_p,
)

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(HERE, "build")
SUFFIX = {"win32": ".dll", "darwin": ".dylib"}.get(sys.platform, ".so")

EMBEDDING_LIB = os.path.join(BUILD_DIR, "libkylin-coreai-embedding-mock" + SUFFIX)
VECTOR_LIB = os.path.join(
    BUILD_DIR, "libkysdk-vector-engine-client-capi-mock" + SUFFIX
)

PASSED = 0


def check(label, ok):
    global PASSED
    assert ok, f"FAILED: {label}"
    PASSED += 1
    print(f"  PASS: {label}")


# ---------------------------------------------------------------- embedding

def verify_embedding():
    print(f"[embedding] loading {EMBEDDING_LIB}")
    lib = ctypes.CDLL(EMBEDDING_LIB)

    lib.text_embedding_create_session.restype = c_void_p
    lib.text_embedding_create_session.argtypes = []
    lib.text_embedding_init_session.restype = c_int
    lib.text_embedding_init_session.argtypes = [c_void_p]
    lib.text_embedding_destroy_session.restype = None
    lib.text_embedding_destroy_session.argtypes = [POINTER(c_void_p)]
    lib.text_embedding_init_model.restype = c_int
    lib.text_embedding_init_model.argtypes = [c_void_p, c_char_p]
    lib.text_embedding.restype = c_bool
    lib.text_embedding.argtypes = [c_void_p, c_char_p, POINTER(c_void_p)]
    lib.embedding_result_get_error_code.restype = c_int
    lib.embedding_result_get_error_code.argtypes = [c_void_p]
    lib.embedding_result_get_vector_data.restype = POINTER(c_float)
    lib.embedding_result_get_vector_data.argtypes = [c_void_p]
    lib.embedding_result_get_vector_length.restype = c_int
    lib.embedding_result_get_vector_length.argtypes = [c_void_p]
    lib.embedding_result_destroy.restype = None
    lib.embedding_result_destroy.argtypes = [POINTER(c_void_p)]

    session = c_void_p(lib.text_embedding_create_session())
    check("create_session returns handle", bool(session.value))
    check("init_session rc == 0", lib.text_embedding_init_session(session) == 0)
    check(
        "init_model rc == 0",
        lib.text_embedding_init_model(session, b"ensemble-embd_gte-base_uint8-text")
        == 0,
    )

    def embed(text: bytes):
        result = c_void_p()
        ok = lib.text_embedding(session, text, byref(result))
        assert ok and result.value, "text_embedding call failed"
        assert lib.embedding_result_get_error_code(result) == 0
        length = lib.embedding_result_get_vector_length(result)
        data = lib.embedding_result_get_vector_data(result)
        vec = [data[i] for i in range(length)]
        lib.embedding_result_destroy(byref(result))
        assert not result.value, "destroy should null the pointer"
        return vec

    v1 = embed("测试文本".encode("utf-8"))
    v2 = embed("测试文本".encode("utf-8"))
    v3 = embed("完全不同的文本".encode("utf-8"))

    check("vector length == 768", len(v1) == 768)
    check("same text -> same vector", v1 == v2)
    check("different text -> different vector", v1 != v3)
    norm = math.sqrt(sum(x * x for x in v1))
    check(f"L2 norm ~= 1 (got {norm:.6f})", abs(norm - 1.0) < 1e-5)

    lib.text_embedding_destroy_session(byref(session))
    check("destroy_session nulls pointer", not session.value)


# ------------------------------------------------------------ vector engine

def verify_vector_engine():
    print(f"[vector_engine] loading {VECTOR_LIB}")
    lib = ctypes.CDLL(VECTOR_LIB)

    lib.vector_engine_create.restype = c_void_p
    lib.vector_engine_create.argtypes = []
    lib.vector_engine_connect.restype = c_int
    lib.vector_engine_connect.argtypes = [c_void_p, c_char_p, c_int]
    lib.vector_engine_disconnect.restype = c_int
    lib.vector_engine_disconnect.argtypes = [c_void_p]
    lib.vector_engine_destroy.restype = None
    lib.vector_engine_destroy.argtypes = [c_void_p]
    lib.vector_engine_create_collection.restype = c_int
    lib.vector_engine_create_collection.argtypes = [c_void_p, c_char_p, c_int]
    lib.vector_engine_load_collection.restype = c_int
    lib.vector_engine_load_collection.argtypes = [c_void_p, c_char_p]
    lib.vector_engine_insert.restype = c_int
    lib.vector_engine_insert.argtypes = [
        c_void_p, c_char_p, c_char_p, c_char_p, POINTER(c_float), c_int
    ]
    lib.vector_engine_hybrid_search.restype = c_int
    lib.vector_engine_hybrid_search.argtypes = [
        c_void_p, c_char_p,
        POINTER(c_float), c_int,
        POINTER(c_uint32), POINTER(c_float), c_int,
        c_int, POINTER(c_char_p),
    ]
    lib.vector_engine_free_buffer.restype = None
    lib.vector_engine_free_buffer.argtypes = [c_void_p]
    lib.vector_engine_get_last_error.restype = c_int
    lib.vector_engine_get_last_error.argtypes = [c_void_p, POINTER(c_char_p)]

    DIM = 768
    engine = lib.vector_engine_create()
    check("create returns handle", bool(engine))

    try:
        check(
            "connect rc == 0",
            lib.vector_engine_connect(engine, b"127.0.0.1", 19530) == 0,
        )
        check(
            "create_collection rc == 0",
            lib.vector_engine_create_collection(engine, b"test", DIM) == 0,
        )
        check(
            "load_collection rc == 0",
            lib.vector_engine_load_collection(engine, b"test") == 0,
        )

        # Insert 3 records; mem_001 dense vector is the "hot" one for the query.
        docs = [
            (b"mem_001", "用户喜欢喝咖啡，尤其是拿铁".encode("utf-8"), 1.0),
            (b"mem_002", "今天天气不错，适合出门散步".encode("utf-8"), 0.0),
            (b"mem_003", "项目截止日期是下周三".encode("utf-8"), 0.0),
        ]
        for i, (mid, content, hot) in enumerate(docs):
            dense = [0.0] * DIM
            dense[i] = 1.0 if hot else 0.5
            arr = (c_float * DIM)(*dense)
            check(
                f"insert {mid.decode()} rc == 0",
                lib.vector_engine_insert(engine, b"test", mid, content, arr, DIM)
                == 0,
            )

        # Query: dense closest to mem_001, sparse tokens overlapping mem_001.
        q_dense = [0.0] * DIM
        q_dense[0] = 1.0
        q_dense_arr = (c_float * DIM)(*q_dense)

        # Sparse query: build indices with the same FNV-1a rule for "咖啡".
        def fnv1a32(data: bytes) -> int:
            h = 2166136261
            for b in data:
                h ^= b
                h = (h * 16777619) & 0xFFFFFFFF
            return h

        tokens = ["咖".encode("utf-8"), "啡".encode("utf-8")]
        idx_arr = (c_uint32 * 2)(*[fnv1a32(t) for t in tokens])
        val_arr = (c_float * 2)(0.5, 0.5)

        out_json = c_char_p()
        rc = lib.vector_engine_hybrid_search(
            engine, b"test", q_dense_arr, DIM, idx_arr, val_arr, 2, 2,
            byref(out_json),
        )
        check("hybrid_search rc == 0", rc == 0)
        check("hybrid_search returned JSON", bool(out_json.value))

        results = json.loads(out_json.value.decode("utf-8"))
        print("  hybrid_search JSON:", json.dumps(results, ensure_ascii=False))
        lib.vector_engine_free_buffer(out_json)

        check("total == 2", results["total"] == 2)
        check("results length == 2", len(results["results"]) == 2)
        top = results["results"][0]
        check("top-1 memory_id == mem_001", top["memory_id"] == "mem_001")
        check("top-1 source == hybrid", top["source"] == "hybrid")
        check(
            "top-1 content round-trips utf-8",
            top["content"] == "用户喜欢喝咖啡，尤其是拿铁",
        )

        # get_last_error on a bad collection name.
        rc = lib.vector_engine_hybrid_search(
            engine, b"no_such", q_dense_arr, DIM, idx_arr, val_arr, 2, 2,
            byref(out_json),
        )
        check("search missing collection rc != 0", rc != 0)
        err = c_char_p()
        check(
            "get_last_error rc == 0",
            lib.vector_engine_get_last_error(engine, byref(err)) == 0,
        )
        check(
            "last_error mentions collection",
            b"collection" in (err.value or b""),
        )
        lib.vector_engine_free_buffer(err)

        check("disconnect rc == 0", lib.vector_engine_disconnect(engine) == 0)
    finally:
        lib.vector_engine_destroy(engine)


def main():
    verify_embedding()
    verify_vector_engine()
    print(f"\nAll {PASSED} checks passed.")


if __name__ == "__main__":
    main()
