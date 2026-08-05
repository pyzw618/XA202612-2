// C API bridge for libkysdk-vector-engine-client.
//
// Wraps VectorDB::Database behind a plain C ABI (see capi/c_api_bridge.h).
// This file is intentionally self-contained: JSON serialization is done by
// hand with std::string, no nlohmann_json dependency is added here.
//
// This bridge requires the openkylin/nile-sp2 SDK API: Database::HybridSearch,
// AnnSearchRequest, RRFRanker, SparseFloatVecFieldData, and CreateIndex.
// It performs true dense+sparse HybridSearch with RRF(k=60); it deliberately
// provides no dense-only fallback for vector_engine_hybrid_search.
#include "c_api_bridge.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <new>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "Database.h"

namespace {

// Field names of the collection layout (see docs/2026-08-02_milvus_c_api_minimal_interface.md 4.1)
constexpr const char* kFieldMemoryId = "memory_id";
constexpr const char* kFieldContent = "content";
constexpr const char* kFieldDenseVector = "dense_vector";
constexpr const char* kFieldSparseVector = "sparse_vector";

struct VectorEngineHandle {
    std::shared_ptr<VectorDB::Database> db;
    std::string last_error;
};

VectorEngineHandle* AsHandle(vector_engine_t engine) {
    return reinterpret_cast<VectorEngineHandle*>(engine);
}

// Record an error message and return the (non-zero) error code.
int SetError(VectorEngineHandle* handle, std::string message, int code) {
    if (handle != nullptr) {
        handle->last_error = std::move(message);
    }
    return code;
}

int SetError(VectorEngineHandle* handle, const VectorDB::Status& status) {
    return SetError(handle, status.Message(), static_cast<int>(status.Code()));
}

// Allocate a C string with malloc; released by vector_engine_free_buffer().
char* DupCString(const std::string& str) {
    char* buffer = static_cast<char*>(std::malloc(str.size() + 1));
    if (buffer == nullptr) {
        return nullptr;
    }
    std::memcpy(buffer, str.data(), str.size());
    buffer[str.size()] = '\0';
    return buffer;
}

// ---------------------------------------------------------------------------
// Sparse vector generation (deterministic hash-based sparse encoding)
// ---------------------------------------------------------------------------

uint32_t Fnv1aHash32(const char* data, size_t size) {
    uint32_t hash = 2166136261u;  // FNV offset basis
    for (size_t i = 0; i < size; ++i) {
        hash ^= static_cast<unsigned char>(data[i]);
        hash *= 16777619u;  // FNV prime
    }
    return hash;
}

bool IsAsciiAlnum(unsigned char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
}

// Length of one UTF-8 code point starting at lead byte `c`.
size_t Utf8CodePointLength(unsigned char c) {
    if ((c & 0x80) == 0) {
        return 1;
    }
    if ((c & 0xE0) == 0xC0) {
        return 2;
    }
    if ((c & 0xF0) == 0xE0) {
        return 3;
    }
    if ((c & 0xF8) == 0xF0) {
        return 4;
    }
    return 1;  // invalid lead byte, treat as single byte
}

// Tokenize `content` and build a sparse vector of (index, tf_weight) pairs.
// ASCII alphanumeric runs become word tokens (case is preserved, matching the
// mock C library and the Python `sparse.py` implementation byte-for-byte);
// every non-ASCII UTF-8 code point (e.g. one Chinese character) becomes its own token.
// Token index = FNV-1a(token) as uint32; weight = count / total_tokens (TF).
std::vector<std::pair<uint32_t, float>> GenerateSparseVector(const std::string& content) {
    std::vector<std::string> tokens;
    std::string current;
    size_t i = 0;
    while (i < content.size()) {
        unsigned char c = static_cast<unsigned char>(content[i]);
        if (c < 0x80) {
            if (IsAsciiAlnum(c)) {
                current.push_back(static_cast<char>(c));
                ++i;
            } else {
                if (!current.empty()) {
                    tokens.push_back(current);
                    current.clear();
                }
                ++i;  // skip ASCII whitespace / punctuation
            }
        } else {
            if (!current.empty()) {
                tokens.push_back(current);
                current.clear();
            }
            size_t len = std::min(Utf8CodePointLength(c), content.size() - i);
            tokens.emplace_back(content.substr(i, len));
            i += len;
        }
    }
    if (!current.empty()) {
        tokens.push_back(current);
    }

    std::vector<std::pair<uint32_t, float>> sparse;
    if (tokens.empty()) {
        return sparse;
    }

    std::unordered_map<uint32_t, uint32_t> counts;
    for (const auto& token : tokens) {
        ++counts[Fnv1aHash32(token.data(), token.size())];
    }

    sparse.reserve(counts.size());
    const float total = static_cast<float>(tokens.size());
    for (const auto& entry : counts) {
        sparse.emplace_back(entry.first, static_cast<float>(entry.second) / total);
    }
    // Deterministic ordering: sort by index, keep max weight on duplicates.
    std::sort(sparse.begin(), sparse.end(),
              [](const auto& lhs, const auto& rhs) { return lhs.first < rhs.first; });
    return sparse;
}

// ---------------------------------------------------------------------------
// JSON helpers (hand-rolled, no external dependency)
// ---------------------------------------------------------------------------

void JsonEscapeInto(const std::string& input, std::string& out) {
    for (char ch : input) {
        unsigned char c = static_cast<unsigned char>(ch);
        switch (c) {
            case '"':
                out += "\\\"";
                break;
            case '\\':
                out += "\\\\";
                break;
            case '\b':
                out += "\\b";
                break;
            case '\f':
                out += "\\f";
                break;
            case '\n':
                out += "\\n";
                break;
            case '\r':
                out += "\\r";
                break;
            case '\t':
                out += "\\t";
                break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out.push_back(ch);  // UTF-8 bytes pass through verbatim
                }
        }
    }
}

std::string JsonEscape(const std::string& input) {
    std::string out;
    out.reserve(input.size() + 8);
    JsonEscapeInto(input, out);
    return out;
}

std::string FormatFloat(float value) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%.6g", static_cast<double>(value));
    return buf;
}

// Escape a value for use inside a Milvus double-quoted string literal.
std::string EscapeMilvusStringLiteral(const std::string& input) {
    std::string out;
    out.reserve(input.size());
    for (char ch : input) {
        if (ch == '"' || ch == '\\') {
            out.push_back('\\');
        }
        out.push_back(ch);
    }
    return out;
}

// ---------------------------------------------------------------------------
// Search implementation
// ---------------------------------------------------------------------------

// Run a dense ANN search on `field_name` and serialize results as:
//   {"results":[{"memory_id":..,"content":..,"score":..,"source":"<source>"}],"total":N}
VectorDB::Status DenseSearchToJson(VectorEngineHandle* handle, const std::string& collection_name,
                                   const float* dense_vector, int dim, int top_k, const char* source,
                                   std::string& out_json) {
    VectorDB::SearchArguments arguments(collection_name, top_k, VectorDB::MetricType::COSINE);
    std::vector<float> query(dense_vector, dense_vector + dim);
    auto status = arguments.AddTargetVector(kFieldDenseVector, std::move(query));
    if (!status.IsOk()) {
        return status;
    }
    arguments.AddOutputField(kFieldMemoryId);
    arguments.AddOutputField(kFieldContent);

    VectorDB::SearchResults results;
    status = handle->db->Search(arguments, results, 0);
    if (!status.IsOk()) {
        return status;
    }

    std::string json = "{\"results\":[";
    int total = 0;
    for (auto& single : results.Results()) {
        const auto& ids = single.Ids();
        const auto& scores = single.Scores();
        const size_t count = scores.size();

        auto id_field = single.OutputField(kFieldMemoryId);
        auto content_field = single.OutputField(kFieldContent);
        auto id_data = id_field ? std::static_pointer_cast<VectorDB::VarCharFieldData>(id_field) : nullptr;
        auto content_data = content_field ? std::static_pointer_cast<VectorDB::VarCharFieldData>(content_field) : nullptr;

        for (size_t i = 0; i < count; ++i) {
            std::string memory_id;
            if (!ids.IsIntegerID()) {
                if (i < ids.StrIDArray().size()) {
                    memory_id = ids.StrIDArray()[i];
                }
            } else if (i < ids.IntIDArray().size()) {
                memory_id = std::to_string(ids.IntIDArray()[i]);
            }
            if (memory_id.empty() && id_data && i < id_data->Data().size()) {
                memory_id = id_data->Data()[i];
            }
            std::string content;
            if (content_data && i < content_data->Data().size()) {
                content = content_data->Data()[i];
            }

            if (total > 0) {
                json.push_back(',');
            }
            json += "{\"memory_id\":\"" + JsonEscape(memory_id) + "\",\"content\":\"" + JsonEscape(content) +
                    "\",\"score\":" + FormatFloat(scores[i]) + ",\"source\":\"" + source + "\"}";
            ++total;
        }
    }
    json += "],\"total\":" + std::to_string(total) + "}";
    out_json = std::move(json);
    return VectorDB::Status::OK();
}

}  // namespace

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

vector_engine_t vector_engine_create() {
    try {
        auto handle = new (std::nothrow) VectorEngineHandle();
        if (handle == nullptr) {
            return nullptr;
        }
        handle->db = VectorDB::Database::Create();
        if (!handle->db) {
            delete handle;
            return nullptr;
        }
        return reinterpret_cast<vector_engine_t>(handle);
    } catch (...) {
        return nullptr;
    }
}

int vector_engine_connect(vector_engine_t engine, const char* app_id, const char* host, int port) {
    auto* handle = AsHandle(engine);
    if (handle == nullptr || !handle->db) {
        return static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR);
    }
    if (app_id == nullptr || app_id[0] == '\0') {
        return SetError(handle, "app_id cannot be empty", static_cast<int>(VectorDB::StatusCode::INVALID_AGUMENT));
    }
    if (port < 1 || port > 65535) {
        return SetError(handle, "port must be between 1 and 65535", static_cast<int>(VectorDB::StatusCode::INVALID_AGUMENT));
    }
    try {
        VectorDB::ConnectParam param(
            app_id,
            host != nullptr ? host : "127.0.0.1",
            static_cast<uint16_t>(port));
        auto status = handle->db->Connect(param);
        if (!status.IsOk()) {
            return SetError(handle, status);
        }
        return 0;
    } catch (const std::exception& e) {
        return SetError(handle, std::string("exception: ") + e.what(),
                        static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
    } catch (...) {
        return SetError(handle, "unknown C++ exception", static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
    }
}

int vector_engine_disconnect(vector_engine_t engine) {
    auto* handle = AsHandle(engine);
    if (handle == nullptr || !handle->db) {
        return static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR);
    }
    try {
        auto status = handle->db->Disconnect();
        if (!status.IsOk()) {
            return SetError(handle, status);
        }
        return 0;
    } catch (...) {
        return SetError(handle, "unknown C++ exception", static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
    }
}

void vector_engine_destroy(vector_engine_t engine) {
    auto* handle = AsHandle(engine);
    if (handle == nullptr) {
        return;
    }
    try {
        delete handle;  // releases the shared_ptr<Database>
    } catch (...) {
    }
}

// ---------------------------------------------------------------------------
// Collection management
// ---------------------------------------------------------------------------

int vector_engine_create_collection(vector_engine_t engine, const char* collection_name, int dim) {
    auto* handle = AsHandle(engine);
    if (handle == nullptr || !handle->db) {
        return static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR);
    }
    if (collection_name == nullptr || dim <= 0) {
        return SetError(handle, "invalid collection name or dimension",
                        static_cast<int>(VectorDB::StatusCode::INVALID_AGUMENT));
    }
    try {
        bool has = false;
        auto status = handle->db->HasCollection(collection_name, has);
        if (!status.IsOk()) {
            return SetError(handle, status);
        }
        if (has) {
            return 0;  // collection already exists
        }

        VectorDB::CollectionSchema schema(collection_name, "memoryhub collection", false);

        VectorDB::FieldSchema id_field(kFieldMemoryId, VectorDB::DataType::VARCHAR, "memory id", true, false);
        id_field.WithMaxLength(128);
        schema.AddField(id_field);

        VectorDB::FieldSchema content_field(kFieldContent, VectorDB::DataType::VARCHAR, "original text");
        content_field.WithMaxLength(4096);
        schema.AddField(content_field);

        VectorDB::FieldSchema dense_field(kFieldDenseVector, VectorDB::DataType::FLOAT_VECTOR, "dense embedding");
        dense_field.WithDimension(static_cast<uint32_t>(dim));
        schema.AddField(dense_field);

        VectorDB::FieldSchema sparse_field(kFieldSparseVector, VectorDB::DataType::SPARSE_FLOAT_VECTOR,
                                           "sparse embedding");
        schema.AddField(sparse_field);

        status = handle->db->CreateCollection(schema);
        if (!status.IsOk()) {
            return SetError(handle, status);
        }

        VectorDB::IndexDesc dense_index(
            kFieldDenseVector, "dense_index", VectorDB::IndexType::FLAT,
            VectorDB::MetricType::COSINE);
        status = handle->db->CreateIndex(collection_name, dense_index);
        if (!status.IsOk()) {
            return SetError(handle, status);
        }

        VectorDB::IndexDesc sparse_index(
            kFieldSparseVector, "sparse_index",
            VectorDB::IndexType::SPARSE_INVERTED_INDEX, VectorDB::MetricType::IP);
        status = handle->db->CreateIndex(collection_name, sparse_index);
        if (!status.IsOk()) {
            return SetError(handle, status);
        }
        return 0;
    } catch (const std::exception& e) {
        return SetError(handle, std::string("exception: ") + e.what(),
                        static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
    } catch (...) {
        return SetError(handle, "unknown C++ exception", static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
    }
}

int vector_engine_load_collection(vector_engine_t engine, const char* collection_name) {
    auto* handle = AsHandle(engine);
    if (handle == nullptr || !handle->db) {
        return static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR);
    }
    try {
        auto status = handle->db->LoadCollection(collection_name != nullptr ? collection_name : "");
        if (!status.IsOk()) {
            return SetError(handle, status);
        }
        return 0;
    } catch (...) {
        return SetError(handle, "unknown C++ exception", static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
    }
}

int vector_engine_release_collection(vector_engine_t engine, const char* collection_name) {
    auto* handle = AsHandle(engine);
    if (handle == nullptr || !handle->db) {
        return static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR);
    }
    try {
        auto status = handle->db->ReleaseCollection(collection_name != nullptr ? collection_name : "");
        if (!status.IsOk()) {
            return SetError(handle, status);
        }
        return 0;
    } catch (...) {
        return SetError(handle, "unknown C++ exception", static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
    }
}

int vector_engine_drop_collection(vector_engine_t engine, const char* collection_name) {
    auto* handle = AsHandle(engine);
    if (handle == nullptr || !handle->db) {
        return static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR);
    }
    try {
        auto status = handle->db->DropCollection(collection_name != nullptr ? collection_name : "");
        if (!status.IsOk()) {
            return SetError(handle, status);
        }
        return 0;
    } catch (...) {
        return SetError(handle, "unknown C++ exception", static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
    }
}

// ---------------------------------------------------------------------------
// Data operations
// ---------------------------------------------------------------------------

int vector_engine_insert(vector_engine_t engine, const char* collection_name, const char* memory_id,
                         const char* content, const float* dense_vector, int dim) {
    auto* handle = AsHandle(engine);
    if (handle == nullptr || !handle->db) {
        return static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR);
    }
    if (collection_name == nullptr || memory_id == nullptr || content == nullptr || dense_vector == nullptr ||
        dim <= 0) {
        return SetError(handle, "invalid insert argument", static_cast<int>(VectorDB::StatusCode::INVALID_AGUMENT));
    }
    try {
        auto sparse = GenerateSparseVector(content);

        std::vector<VectorDB::FieldDataPtr> fields;
        fields.emplace_back(
            std::make_shared<VectorDB::VarCharFieldData>(kFieldMemoryId, std::vector<std::string>{memory_id}));
        fields.emplace_back(
            std::make_shared<VectorDB::VarCharFieldData>(kFieldContent, std::vector<std::string>{content}));
        fields.emplace_back(std::make_shared<VectorDB::FloatVecFieldData>(
            kFieldDenseVector, std::vector<std::vector<float>>{
                std::vector<float>(dense_vector, dense_vector + dim)}));
        fields.emplace_back(std::make_shared<VectorDB::SparseFloatVecFieldData>(
            kFieldSparseVector,
            std::vector<std::vector<std::pair<uint32_t, float>>>{std::move(sparse)}));

        VectorDB::DmlResults results;
        auto status = handle->db->Insert(collection_name, fields, results);
        if (!status.IsOk()) {
            return SetError(handle, status);
        }
        return 0;
    } catch (const std::exception& e) {
        return SetError(handle, std::string("exception: ") + e.what(),
                        static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
    } catch (...) {
        return SetError(handle, "unknown C++ exception", static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
    }
}

int vector_engine_delete(vector_engine_t engine, const char* collection_name, const char* memory_id) {
    auto* handle = AsHandle(engine);
    if (handle == nullptr || !handle->db) {
        return static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR);
    }
    if (collection_name == nullptr || memory_id == nullptr) {
        return SetError(handle, "invalid delete argument", static_cast<int>(VectorDB::StatusCode::INVALID_AGUMENT));
    }
    try {
        // memory_id is a VARCHAR primary key, so it must be quoted.
        std::string expression =
            std::string(kFieldMemoryId) + " in [\"" + EscapeMilvusStringLiteral(memory_id) + "\"]";
        VectorDB::DmlResults results;
        auto status = handle->db->Delete(collection_name, expression, results);
        if (!status.IsOk()) {
            return SetError(handle, status);
        }
        return 0;
    } catch (...) {
        return SetError(handle, "unknown C++ exception", static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
    }
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

int vector_engine_hybrid_search(vector_engine_t engine, const char* collection_name, const float* dense_vector,
                                int dim, const uint32_t* sparse_indices, const float* sparse_values,
                                int sparse_count, int top_k, char** out_json) {
    if (out_json != nullptr) {
        *out_json = nullptr;
    }
    auto* handle = AsHandle(engine);
    if (handle == nullptr || !handle->db) {
        return static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR);
    }
    if (collection_name == nullptr || dense_vector == nullptr || dim <= 0 ||
        sparse_count < 0 || top_k <= 0 || out_json == nullptr ||
        (sparse_count > 0 && (sparse_indices == nullptr || sparse_values == nullptr))) {
        return SetError(handle, "invalid hybrid search argument",
                        static_cast<int>(VectorDB::StatusCode::INVALID_AGUMENT));
    }
    try {
        VectorDB::AnnSearchRequest dense_request(kFieldDenseVector, top_k);
        auto status = dense_request.AddTargetVector(
            kFieldDenseVector, std::vector<float>(dense_vector, dense_vector + dim));
        if (!status.IsOk()) {
            return SetError(handle, status);
        }

        std::vector<std::pair<uint32_t, float>> sparse;
        sparse.reserve(static_cast<size_t>(sparse_count));
        for (int i = 0; i < sparse_count; ++i) {
            sparse.emplace_back(sparse_indices[i], sparse_values[i]);
        }
        VectorDB::AnnSearchRequest sparse_request(kFieldSparseVector, top_k);
        status = sparse_request.AddTargetVector(kFieldSparseVector, std::move(sparse));
        if (!status.IsOk()) {
            return SetError(handle, status);
        }

        VectorDB::RRFRanker ranker(60.0F);
        VectorDB::SearchResults results;
        status = handle->db->HybridSearch(
            results, collection_name, {dense_request, sparse_request}, ranker, top_k,
            {kFieldMemoryId, kFieldContent}, {}, 0);
        if (!status.IsOk()) {
            return SetError(handle, status);
        }

        std::string json = "{\"results\":[";
        int total = 0;
        for (const auto& single : results.Results()) {
            const auto& ids = single.Ids();
            const auto& scores = single.Scores();
            auto id_field = single.OutputField(kFieldMemoryId);
            auto content_field = single.OutputField(kFieldContent);
            auto id_data = id_field
                ? std::static_pointer_cast<VectorDB::VarCharFieldData>(id_field)
                : nullptr;
            auto content_data = content_field
                ? std::static_pointer_cast<VectorDB::VarCharFieldData>(content_field)
                : nullptr;
            for (size_t i = 0; i < scores.size(); ++i) {
                std::string memory_id;
                if (!ids.IsIntegerID() && i < ids.StrIDArray().size()) {
                    memory_id = ids.StrIDArray()[i];
                } else if (ids.IsIntegerID() && i < ids.IntIDArray().size()) {
                    memory_id = std::to_string(ids.IntIDArray()[i]);
                }
                if (memory_id.empty() && id_data && i < id_data->Data().size()) {
                    memory_id = id_data->Data()[i];
                }
                std::string content;
                if (content_data && i < content_data->Data().size()) {
                    content = content_data->Data()[i];
                }
                if (total++ > 0) {
                    json.push_back(',');
                }
                json += "{\"memory_id\":\"" + JsonEscape(memory_id)
                    + "\",\"content\":\"" + JsonEscape(content)
                    + "\",\"score\":" + FormatFloat(scores[i])
                    + ",\"source\":\"hybrid\"}";
            }
        }
        json += "],\"total\":" + std::to_string(total) + "}";
        *out_json = DupCString(json);
        if (*out_json == nullptr) {
            return SetError(handle, "out of memory",
                            static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
        }
        return 0;
    } catch (const std::exception& e) {
        return SetError(handle, std::string("exception: ") + e.what(),
                        static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
    } catch (...) {
        return SetError(handle, "unknown C++ exception",
                        static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
    }
}

int vector_engine_dense_search(vector_engine_t engine, const char* collection_name, const float* dense_vector,
                               int dim, int top_k, char** out_json) {
    if (out_json != nullptr) {
        *out_json = nullptr;
    }
    auto* handle = AsHandle(engine);
    if (handle == nullptr || !handle->db) {
        return static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR);
    }
    if (collection_name == nullptr || dense_vector == nullptr || dim <= 0 || top_k <= 0 || out_json == nullptr) {
        return SetError(handle, "invalid search argument", static_cast<int>(VectorDB::StatusCode::INVALID_AGUMENT));
    }
    try {
        std::string json;
        auto status = DenseSearchToJson(handle, collection_name, dense_vector, dim, top_k, "dense", json);
        if (!status.IsOk()) {
            return SetError(handle, status);
        }
        *out_json = DupCString(json);
        if (*out_json == nullptr) {
            return SetError(handle, "out of memory", static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
        }
        return 0;
    } catch (const std::exception& e) {
        return SetError(handle, std::string("exception: ") + e.what(),
                        static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
    } catch (...) {
        return SetError(handle, "unknown C++ exception", static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR));
    }
}

int vector_engine_sparse_search(vector_engine_t engine, const char* collection_name, const uint32_t* sparse_indices,
                                const float* sparse_values, int sparse_count, int top_k, char** out_json) {
    if (out_json != nullptr) {
        *out_json = nullptr;
    }
    auto* handle = AsHandle(engine);
    if (handle == nullptr || !handle->db) {
        return static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR);
    }
    (void)collection_name;
    (void)sparse_indices;
    (void)sparse_values;
    (void)sparse_count;
    (void)top_k;
    // This SDK branch cannot issue a sparse-vector search through the public
    // API (SearchArguments only accepts float/binary target vectors).
    return SetError(handle, "sparse search is not supported by this SDK branch (no sparse target vector API)",
                    static_cast<int>(VectorDB::StatusCode::NOT_SUPPORTED));
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

void vector_engine_free_buffer(void* buffer) {
    std::free(buffer);
}

int vector_engine_get_last_error(vector_engine_t engine, char** out_message) {
    if (out_message == nullptr) {
        return static_cast<int>(VectorDB::StatusCode::INVALID_AGUMENT);
    }
    *out_message = nullptr;
    auto* handle = AsHandle(engine);
    if (handle == nullptr) {
        *out_message = DupCString("engine handle is NULL");
        return static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR);
    }
    try {
        *out_message = DupCString(handle->last_error);
        if (*out_message == nullptr) {
            return static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR);
        }
        return 0;
    } catch (...) {
        return static_cast<int>(VectorDB::StatusCode::UNKNOWN_ERROR);
    }
}
