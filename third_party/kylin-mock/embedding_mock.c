/*
 * embedding_mock.c — Mock implementation of libkylin-coreai-embedding C API.
 *
 * Exports the same symbols as the real kylin-coreai-embedding SDK so that the
 * Python ctypes wrapper (memoryhub/embedding/kylin_client.py) can run on
 * machines without Kylin OS / DBus.
 *
 * Behavior:
 *   - text_embedding(): deterministic 768-dim float vector derived from an
 *     FNV-1a hash of the input text (same text -> same vector), L2-normalized.
 *   - Optional artificial latency via env var KYLIN_EMBEDDING_MOCK_LATENCY_MS.
 *   - Async API reports "not supported" via the callback's result error code.
 *
 * Pure C + libc (+libm), no DBus/GObject. Builds on Windows and Linux.
 */

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#ifdef _WIN32
#include <windows.h>
#define KYLIN_EXPORT __declspec(dllexport)
static void mock_sleep_ms(long ms) {
    if (ms > 0) Sleep((DWORD)ms);
}
#else
#include <time.h>
#define KYLIN_EXPORT __attribute__((visibility("default")))
static void mock_sleep_ms(long ms) {
    if (ms <= 0) return;
    struct timespec ts;
    ts.tv_sec = ms / 1000;
    ts.tv_nsec = (ms % 1000) * 1000000L;
    nanosleep(&ts, NULL);
}
#endif

/* ---- Error codes (matches CoreAiEmbeddingErrorCode) ---- */
typedef enum {
    COREAI_EMBEDDING_SUCESS = 0, /* deprecated misspelling kept for parity */
    COREAI_EMBEDDING_SUCCESS = 0,
    COREAI_EMBEDDING_INPUT_ERROR,
    COREAI_EMBEDDING_INIT_ERROR,
    COREAI_EMBEDDING_CONNECTION_ERROR,
    COREAI_EMBEDDING_RUNTIME_ERROR,
    COREAI_EMBEDDING_ERROR_UNKNOWN = 99,
} CoreAiEmbeddingErrorCode;

#define MOCK_DIM 768
#define MOCK_MODEL_TEXT "ensemble-embd_gte-base_uint8-text"
#define MOCK_MODEL_IMAGE "ensemble-embd_cn-clip_512-uint8-text|embd_cn-clip_512-uint8-image"

/* ---- Internal structures (opaque to callers) ---- */

typedef struct _EmbeddingModelInfo {
    char model_name[160];
    int dim;
} EmbeddingModelInfo;

typedef struct _EmbeddingModelList {
    EmbeddingModelInfo models[2];
    int count;
} EmbeddingModelList;

typedef struct _TextEmbeddingSession {
    int initialized;
    int model_loaded;
    char model_name[160];
    bool internal_event_loop;
    EmbeddingModelList model_list;
    int model_list_ready;
} TextEmbeddingSession;

typedef struct _EmbeddingResult {
    int error_code;
    char error_message[256];
    float *vector;
    int vector_length;
} EmbeddingResult;

typedef void (*TextEmbeddingResultCallback)(EmbeddingResult *result,
                                            void *callback_user_data);

/* ---- Helpers ---- */

static long mock_latency_ms(void) {
    const char *env = getenv("KYLIN_EMBEDDING_MOCK_LATENCY_MS");
    if (!env || !*env) return 0;
    long v = strtol(env, NULL, 10);
    return v > 0 ? v : 0;
}

/* FNV-1a 64-bit over UTF-8 bytes. */
static uint64_t fnv1a64(const char *s) {
    uint64_t h = 14695981039346656037ULL;
    const unsigned char *p = (const unsigned char *)s;
    while (*p) {
        h ^= (uint64_t)(*p++);
        h *= 1099511628211ULL;
    }
    return h;
}

/* xorshift32 PRNG seeded from the text hash -> deterministic vector. */
static uint32_t xorshift32(uint32_t *state) {
    uint32_t x = *state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    *state = x;
    return x;
}

static void mock_embed_text(const char *text, float *out, int dim) {
    uint64_t h = fnv1a64(text);
    uint32_t state = (uint32_t)(h ^ (h >> 32));
    if (state == 0) state = 0x9E3779B9u; /* avoid degenerate seed */
    double norm = 0.0;
    int i;
    for (i = 0; i < dim; i++) {
        /* uniform in [-1, 1) */
        float v = ((float)xorshift32(&state) / 4294967296.0f) * 2.0f - 1.0f;
        out[i] = v;
        norm += (double)v * (double)v;
    }
    norm = sqrt(norm);
    if (norm > 0.0) {
        for (i = 0; i < dim; i++) out[i] = (float)((double)out[i] / norm);
    }
}

static void fill_model_list(TextEmbeddingSession *session) {
    EmbeddingModelList *list = &session->model_list;
    memset(list, 0, sizeof(*list));
    list->count = 2;
    strncpy(list->models[0].model_name, MOCK_MODEL_IMAGE,
            sizeof(list->models[0].model_name) - 1);
    list->models[0].dim = 1024;
    strncpy(list->models[1].model_name, MOCK_MODEL_TEXT,
            sizeof(list->models[1].model_name) - 1);
    list->models[1].dim = MOCK_DIM;
    session->model_list_ready = 1;
}

static void set_error(int *error_code, int code) {
    if (error_code) *error_code = code;
}

/* ---- Lifecycle ---- */

KYLIN_EXPORT TextEmbeddingSession *text_embedding_create_session(void) {
    TextEmbeddingSession *session =
        (TextEmbeddingSession *)calloc(1, sizeof(TextEmbeddingSession));
    return session;
}

KYLIN_EXPORT int text_embedding_init_session(TextEmbeddingSession *session) {
    if (!session) return COREAI_EMBEDDING_INPUT_ERROR;
    mock_sleep_ms(mock_latency_ms());
    session->initialized = 1;
    return COREAI_EMBEDDING_SUCCESS;
}

KYLIN_EXPORT void text_embedding_destroy_session(TextEmbeddingSession **session) {
    if (!session || !*session) return;
    free(*session);
    *session = NULL;
}

KYLIN_EXPORT EmbeddingModelList *text_embedding_get_model_list(
    TextEmbeddingSession *session, int *error_code) {
    if (!session || !session->initialized) {
        set_error(error_code, COREAI_EMBEDDING_INIT_ERROR);
        return NULL;
    }
    if (!session->model_list_ready) fill_model_list(session);
    set_error(error_code, COREAI_EMBEDDING_SUCCESS);
    return &session->model_list;
}

/* ---- Model operations ---- */

KYLIN_EXPORT int text_embedding_init_model(TextEmbeddingSession *session,
                                           const char *model_name) {
    if (!session || !model_name) return COREAI_EMBEDDING_INPUT_ERROR;
    if (!session->initialized) return COREAI_EMBEDDING_INIT_ERROR;
    mock_sleep_ms(mock_latency_ms());
    strncpy(session->model_name, model_name, sizeof(session->model_name) - 1);
    session->model_loaded = 1;
    return COREAI_EMBEDDING_SUCCESS;
}

KYLIN_EXPORT bool text_embedding_get_model_info(TextEmbeddingSession *session,
                                                char **model_info) {
    /* Deprecated API kept for symbol parity. Caller owns the returned string. */
    static const char *json =
        "{\"models\":[{\"dim\":768,\"model\":\"" MOCK_MODEL_TEXT "\"}]}";
    size_t len;
    if (!session || !model_info) return false;
    len = strlen(json) + 1;
    *model_info = (char *)malloc(len);
    if (!*model_info) return false;
    memcpy(*model_info, json, len);
    return true;
}

KYLIN_EXPORT int embedding_model_list_get_count(const EmbeddingModelList *model_list,
                                                int *error_code) {
    if (!model_list) {
        set_error(error_code, COREAI_EMBEDDING_INPUT_ERROR);
        return 0;
    }
    set_error(error_code, COREAI_EMBEDDING_SUCCESS);
    return model_list->count;
}

KYLIN_EXPORT const EmbeddingModelInfo *embedding_model_list_get_model(
    const EmbeddingModelList *model_list, int index, int *error_code) {
    if (!model_list || index < 0 || index >= model_list->count) {
        set_error(error_code, COREAI_EMBEDDING_INPUT_ERROR);
        return NULL;
    }
    set_error(error_code, COREAI_EMBEDDING_SUCCESS);
    return &model_list->models[index];
}

KYLIN_EXPORT const char *embedding_model_info_get_model_name(
    const EmbeddingModelInfo *model_info, int *error_code) {
    if (!model_info) {
        set_error(error_code, COREAI_EMBEDDING_INPUT_ERROR);
        return NULL;
    }
    set_error(error_code, COREAI_EMBEDDING_SUCCESS);
    return model_info->model_name;
}

KYLIN_EXPORT int embedding_model_info_get_model_dim(
    const EmbeddingModelInfo *model_info, int *error_code) {
    if (!model_info) {
        set_error(error_code, COREAI_EMBEDDING_INPUT_ERROR);
        return 0;
    }
    set_error(error_code, COREAI_EMBEDDING_SUCCESS);
    return model_info->dim;
}

/* ---- Synchronous inference ---- */

KYLIN_EXPORT bool text_embedding(TextEmbeddingSession *session, const char *text,
                                 EmbeddingResult **result) {
    EmbeddingResult *res;
    if (!session || !text || !result) return false;

    res = (EmbeddingResult *)calloc(1, sizeof(EmbeddingResult));
    if (!res) return false;
    *result = res;

    if (!session->initialized || !session->model_loaded) {
        res->error_code = COREAI_EMBEDDING_INIT_ERROR;
        snprintf(res->error_message, sizeof(res->error_message),
                 "session not initialized or model not loaded");
        return true;
    }

    mock_sleep_ms(mock_latency_ms());

    res->vector = (float *)malloc(sizeof(float) * MOCK_DIM);
    if (!res->vector) {
        res->error_code = COREAI_EMBEDDING_RUNTIME_ERROR;
        snprintf(res->error_message, sizeof(res->error_message), "out of memory");
        return true;
    }
    mock_embed_text(text, res->vector, MOCK_DIM);
    res->vector_length = MOCK_DIM;
    res->error_code = COREAI_EMBEDDING_SUCCESS;
    res->error_message[0] = '\0';
    return true;
}

KYLIN_EXPORT int embedding_result_get_error_code(EmbeddingResult *result) {
    if (!result) return COREAI_EMBEDDING_INPUT_ERROR;
    return result->error_code;
}

KYLIN_EXPORT const char *embedding_result_get_error_message(EmbeddingResult *result) {
    if (!result) return NULL;
    return result->error_message;
}

KYLIN_EXPORT float *embedding_result_get_vector_data(EmbeddingResult *result) {
    if (!result) return NULL;
    return result->vector;
}

KYLIN_EXPORT int embedding_result_get_vector_length(EmbeddingResult *result) {
    if (!result) return 0;
    return result->vector_length;
}

KYLIN_EXPORT void embedding_result_destroy(EmbeddingResult **result) {
    if (!result || !*result) return;
    free((*result)->vector);
    free(*result);
    *result = NULL;
}

/* ---- Async inference (not supported by the mock) ---- */

KYLIN_EXPORT void text_embedding_async(TextEmbeddingSession *session, const char *text,
                                       TextEmbeddingResultCallback callback,
                                       void *callback_user_data) {
    EmbeddingResult res;
    (void)text;
    if (!callback) return;
    memset(&res, 0, sizeof(res));
    if (!session || !session->initialized) {
        res.error_code = COREAI_EMBEDDING_INIT_ERROR;
        snprintf(res.error_message, sizeof(res.error_message),
                 "session not initialized");
    } else {
        res.error_code = COREAI_EMBEDDING_ERROR_UNKNOWN;
        snprintf(res.error_message, sizeof(res.error_message),
                 "async inference not supported by mock");
    }
    /* Result lifetime is callback scope; freed implicitly (stack). */
    callback(&res, callback_user_data);
}

KYLIN_EXPORT void text_embedding_enable_internal_event_loop(
    TextEmbeddingSession *session, bool enable) {
    if (!session) return;
    session->internal_event_loop = enable;
}
