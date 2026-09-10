// C API bridge for libkysdk-vector-engine-client.
//
// Exposes the VectorDB::Database C++ SDK as a plain C ABI so that
// foreign-language consumers (e.g. Python ctypes) can use it.
// See docs/2026-08-02_milvus_c_api_minimal_interface.md for the contract.

#ifndef KYLIN_VECTOR_ENGINE_CAPI_H
#define KYLIN_VECTOR_ENGINE_CAPI_H

#include <stdint.h>

#if defined(_MSC_VER)
#define VE_CAPI_EXPORT __declspec(dllexport)
#elif defined(__GNUC__) || defined(__clang__)
#define VE_CAPI_EXPORT __attribute__((visibility("default")))
#else
#define VE_CAPI_EXPORT
#endif

#ifdef __cplusplus
extern "C" {
#endif

// Opaque engine handle
typedef void* vector_engine_t;

// Free function type for buffers returned by this library
typedef void (*vector_engine_free_fn)(void* ptr);

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

// Create a VectorDB::Database instance (currently MilvusClientImpl).
// Returns engine handle, NULL on failure.
VE_CAPI_EXPORT vector_engine_t vector_engine_create();

// Connect to the vector service with the non-empty SDK application identity.
// An empty host selects Kylin's per-user Unix socket; a non-empty host selects
// the explicit host:port endpoint.
// Returns 0 on success, non-zero StatusCode on failure.
VE_CAPI_EXPORT int vector_engine_connect(vector_engine_t engine, const char* app_id, const char* host, int port);

// Ask the local Kylin vector service to open/create its persistent database.
// `encrypt` is treated as a boolean.  `key` may be empty when encryption is off.
VE_CAPI_EXPORT int vector_engine_load_db_file(vector_engine_t engine, const char* db_file, int encrypt,
                                              const char* key);

// Disconnect from Milvus. Returns 0 on success, non-zero on failure.
VE_CAPI_EXPORT int vector_engine_disconnect(vector_engine_t engine);

// Destroy the engine instance. The handle is invalid after this call.
VE_CAPI_EXPORT void vector_engine_destroy(vector_engine_t engine);

// ---------------------------------------------------------------------------
// Collection management
// ---------------------------------------------------------------------------

// Create a collection with fields:
//   memory_id     VARCHAR(128) primary key
//   content       VARCHAR(4096)
//   dense_vector  FLOAT_VECTOR(dim)
//   sparse_vector SPARSE_FLOAT_VECTOR
// Creates FLAT/COSINE and SPARSE_INVERTED_INDEX/IP indexes.
// If the collection already exists, returns 0 immediately.
VE_CAPI_EXPORT int vector_engine_create_collection(vector_engine_t engine, const char* collection_name, int dim);

// Load collection into query node memory. Returns 0 on success.
VE_CAPI_EXPORT int vector_engine_load_collection(vector_engine_t engine, const char* collection_name);

// Release collection from query node memory. Returns 0 on success.
VE_CAPI_EXPORT int vector_engine_release_collection(vector_engine_t engine, const char* collection_name);

// Drop a collection with all its data. Returns 0 on success.
VE_CAPI_EXPORT int vector_engine_drop_collection(vector_engine_t engine, const char* collection_name);

// ---------------------------------------------------------------------------
// Data operations
// ---------------------------------------------------------------------------

// Insert one memory record. The sparse vector is derived from `content`
// inside the bridge (deterministic hash-based sparse encoding).
VE_CAPI_EXPORT int vector_engine_insert(vector_engine_t engine, const char* collection_name, const char* memory_id,
                                        const char* content, const float* dense_vector, int dim);

// Delete records by memory_id (VARCHAR primary key). Returns 0 on success.
VE_CAPI_EXPORT int vector_engine_delete(vector_engine_t engine, const char* collection_name, const char* memory_id);

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

// Hybrid search over dense_vector and sparse_vector, fused with RRF (k=60).
// out_json receives a malloc'ed JSON string:
//   {"results":[{"memory_id":..,"content":..,"score":..,"source":"hybrid"}],"total":N}
// The caller must free it with vector_engine_free_buffer().
VE_CAPI_EXPORT int vector_engine_hybrid_search(vector_engine_t engine, const char* collection_name,
                                               const float* dense_vector, int dim, const uint32_t* sparse_indices,
                                               const float* sparse_values, int sparse_count, int top_k,
                                               char** out_json);

// Dense-only search (debug/benchmark). Same JSON format, source="dense".
VE_CAPI_EXPORT int vector_engine_dense_search(vector_engine_t engine, const char* collection_name,
                                              const float* dense_vector, int dim, int top_k, char** out_json);

// Sparse-only search (debug/benchmark). Same JSON format, source="sparse".
VE_CAPI_EXPORT int vector_engine_sparse_search(vector_engine_t engine, const char* collection_name,
                                               const uint32_t* sparse_indices, const float* sparse_values,
                                               int sparse_count, int top_k, char** out_json);

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

// Free a string buffer returned by this library (out_json / out_message).
VE_CAPI_EXPORT void vector_engine_free_buffer(void* buffer);

// Get the last error message of this engine. out_message receives a malloc'ed
// string which the caller must free with vector_engine_free_buffer().
VE_CAPI_EXPORT int vector_engine_get_last_error(vector_engine_t engine, char** out_message);

#ifdef __cplusplus
}
#endif

#endif  // KYLIN_VECTOR_ENGINE_CAPI_H
