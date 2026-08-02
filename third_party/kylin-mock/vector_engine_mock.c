/*
 * vector_engine_mock.c — Mock implementation of the Kylin vector engine
 * minimal C API (libkysdk-vector-engine-client-capi).
 *
 * Exports the exact function names/signatures defined in
 * docs/2026-08-02_milvus_c_api_minimal_interface.md so the Python ctypes
 * wrapper (memoryhub/storage/vector_engine/_milvus_ctypes.py) can run without
 * a Milvus server.
 *
 * Behavior:
 *   - In-memory collections: list of (memory_id, content, dense_vector).
 *   - Sparse vectors derived from content with the same rule as the real
 *     bridge layer: split tokens on non-alphanumeric/whitespace, CJK
 *     characters as single-char tokens, FNV-1a 32-bit hash as index,
 *     weight = normalized TF.
 *   - hybrid_search: cosine top-k on dense + dot-product top-k on sparse,
 *     fused with RRF (score = sum of 1/(60 + rank)).
 *   - Search results are returned as malloc'd JSON strings, released with
 *     vector_engine_free_buffer.
 *
 * Pure C + libc (+libm on Linux). No Milvus/gRPC dependency.
 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#ifdef _WIN32
#define KYLIN_EXPORT __declspec(dllexport)
#else
#define KYLIN_EXPORT __attribute__((visibility("default")))
#endif

typedef void *vector_engine_t;

/* Forward declaration: vector_engine_insert uses it for upsert. */
KYLIN_EXPORT int vector_engine_delete(vector_engine_t engine,
                                      const char *collection_name,
                                      const char *memory_id);

/* ---------------- Data structures ---------------- */

typedef struct Record {
    char *memory_id;
    char *content;
    float *dense;
    int dim;
    uint32_t *sp_idx; /* sparse vector generated from content */
    float *sp_val;
    int sp_count;
    struct Record *next;
} Record;

typedef struct Collection {
    char *name;
    int dim;
    int loaded;
    Record *records;
    struct Collection *next;
} Collection;

typedef struct Engine {
    int connected;
    char *last_error;
    Collection *collections;
} Engine;

/* ---------------- Small utilities ---------------- */

static char *mock_strdup(const char *s) {
    size_t len = strlen(s) + 1;
    char *copy = (char *)malloc(len);
    if (copy) memcpy(copy, s, len);
    return copy;
}

static void set_last_error(Engine *engine, const char *msg) {
    if (!engine) return;
    free(engine->last_error);
    engine->last_error = msg ? mock_strdup(msg) : NULL;
}

static Collection *find_collection(Engine *engine, const char *name) {
    Collection *c;
    if (!engine || !name) return NULL;
    for (c = engine->collections; c; c = c->next) {
        if (strcmp(c->name, name) == 0) return c;
    }
    return NULL;
}

/* ---------------- Sparse vector from content ----------------
 * Tokenize: ASCII alphanumeric runs are tokens; CJK (any non-ASCII UTF-8
 * codepoint) is a single-char token; everything else is a delimiter.
 * index = FNV-1a 32-bit of token bytes, weight = count / total_tokens.
 */

static uint32_t fnv1a32(const unsigned char *s, size_t len) {
    uint32_t h = 2166136261u;
    size_t i;
    for (i = 0; i < len; i++) {
        h ^= (uint32_t)s[i];
        h *= 16777619u;
    }
    return h;
}

static int utf8_char_len(unsigned char lead) {
    if (lead < 0x80) return 1;
    if ((lead & 0xE0) == 0xC0) return 2;
    if ((lead & 0xF0) == 0xE0) return 3;
    if ((lead & 0xF8) == 0xF0) return 4;
    return 1; /* invalid byte: treat as single */
}

static int is_alnum_ascii(unsigned char c) {
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') ||
           (c >= 'A' && c <= 'Z');
}

/* Accumulate one token hash into (idx, count) arrays; returns new count. */
static int accum_token(uint32_t **idx, int **cnt, int *cap, int n, uint32_t h) {
    int i;
    for (i = 0; i < n; i++) {
        if ((*idx)[i] == h) {
            (*cnt)[i]++;
            return n;
        }
    }
    if (n == *cap) {
        int new_cap = (*cap == 0) ? 16 : (*cap * 2);
        uint32_t *ni = (uint32_t *)realloc(*idx, sizeof(uint32_t) * new_cap);
        int *nc;
        if (!ni) return -1;
        *idx = ni;
        nc = (int *)realloc(*cnt, sizeof(int) * new_cap);
        if (!nc) return -1;
        *cnt = nc;
        *cap = new_cap;
    }
    (*idx)[n] = h;
    (*cnt)[n] = 1;
    return n + 1;
}

/* Build sparse vector from text. Returns 0 on success. */
static int sparse_from_text(const char *text, uint32_t **out_idx,
                            float **out_val, int *out_count) {
    const unsigned char *p = (const unsigned char *)text;
    uint32_t *idx = NULL;
    int *cnt = NULL;
    int cap = 0, n = 0, total = 0;
    float *val = NULL;
    int i;

    while (*p) {
        unsigned char c = *p;
        if (c >= 0x80) {
            /* CJK / non-ASCII: whole codepoint is one token */
            int len = utf8_char_len(c);
            n = accum_token(&idx, &cnt, &cap, n, fnv1a32(p, (size_t)len));
            if (n < 0) goto oom;
            total++;
            p += len;
        } else if (is_alnum_ascii(c)) {
            const unsigned char *start = p;
            while (is_alnum_ascii(*p)) p++;
            n = accum_token(&idx, &cnt, &cap, n,
                            fnv1a32(start, (size_t)(p - start)));
            if (n < 0) goto oom;
            total++;
        } else {
            p++; /* delimiter */
        }
    }

    if (n == 0) {
        free(idx);
        free(cnt);
        *out_idx = NULL;
        *out_val = NULL;
        *out_count = 0;
        return 0;
    }

    val = (float *)malloc(sizeof(float) * n);
    if (!val) goto oom;
    for (i = 0; i < n; i++) val[i] = (float)cnt[i] / (float)total;
    free(cnt);
    *out_idx = idx;
    *out_val = val;
    *out_count = n;
    return 0;

oom:
    free(idx);
    free(cnt);
    return -1;
}

static double sparse_dot(const uint32_t *a_idx, const float *a_val, int a_n,
                         const uint32_t *b_idx, const float *b_val, int b_n) {
    double sum = 0.0;
    int i, j;
    for (i = 0; i < a_n; i++) {
        for (j = 0; j < b_n; j++) {
            if (a_idx[i] == b_idx[j]) {
                sum += (double)a_val[i] * (double)b_val[j];
                break;
            }
        }
    }
    return sum;
}

static double cosine(const float *a, const float *b, int dim) {
    double dot = 0.0, na = 0.0, nb = 0.0;
    int i;
    for (i = 0; i < dim; i++) {
        dot += (double)a[i] * (double)b[i];
        na += (double)a[i] * (double)a[i];
        nb += (double)b[i] * (double)b[i];
    }
    if (na <= 0.0 || nb <= 0.0) return 0.0;
    return dot / (sqrt(na) * sqrt(nb));
}

/* ---------------- JSON builder ---------------- */

typedef struct {
    char *buf;
    size_t len;
    size_t cap;
} JsonBuf;

static int jb_init(JsonBuf *jb) {
    jb->cap = 256;
    jb->len = 0;
    jb->buf = (char *)malloc(jb->cap);
    if (!jb->buf) return -1;
    jb->buf[0] = '\0';
    return 0;
}

static int jb_ensure(JsonBuf *jb, size_t extra) {
    if (jb->len + extra + 1 <= jb->cap) return 0;
    while (jb->len + extra + 1 > jb->cap) jb->cap *= 2;
    {
        char *nb = (char *)realloc(jb->buf, jb->cap);
        if (!nb) return -1;
        jb->buf = nb;
    }
    return 0;
}

static int jb_append(JsonBuf *jb, const char *s) {
    size_t n = strlen(s);
    if (jb_ensure(jb, n) != 0) return -1;
    memcpy(jb->buf + jb->len, s, n + 1);
    jb->len += n;
    return 0;
}

/* Append a JSON-escaped string (with surrounding quotes). */
static int jb_append_json_string(JsonBuf *jb, const char *s) {
    const unsigned char *p = (const unsigned char *)s;
    char tmp[8];
    if (jb_append(jb, "\"") != 0) return -1;
    while (*p) {
        unsigned char c = *p;
        const char *esc = NULL;
        switch (c) {
        case '"': esc = "\\\""; break;
        case '\\': esc = "\\\\"; break;
        case '\n': esc = "\\n"; break;
        case '\r': esc = "\\r"; break;
        case '\t': esc = "\\t"; break;
        case '\b': esc = "\\b"; break;
        case '\f': esc = "\\f"; break;
        default: break;
        }
        if (esc) {
            if (jb_append(jb, esc) != 0) return -1;
            p++;
        } else if (c < 0x20) {
            snprintf(tmp, sizeof(tmp), "\\u%04x", (unsigned)c);
            if (jb_append(jb, tmp) != 0) return -1;
            p++;
        } else {
            /* ASCII or UTF-8 continuation: pass through verbatim */
            if (jb_ensure(jb, 1) != 0) return -1;
            jb->buf[jb->len++] = (char)c;
            jb->buf[jb->len] = '\0';
            p++;
        }
    }
    return jb_append(jb, "\"");
}

/* ---------------- Record / collection teardown ---------------- */

static void free_record(Record *r) {
    if (!r) return;
    free(r->memory_id);
    free(r->content);
    free(r->dense);
    free(r->sp_idx);
    free(r->sp_val);
    free(r);
}

static void free_collection(Collection *c) {
    Record *r;
    if (!c) return;
    r = c->records;
    while (r) {
        Record *next = r->next;
        free_record(r);
        r = next;
    }
    free(c->name);
    free(c);
}

/* ---------------- Ranking ---------------- */

typedef struct {
    Record *rec;
    double score;   /* per-route score (cosine or sparse dot) */
    int rank;       /* 1-based rank within a route; 0 = not ranked */
    double fused;   /* RRF fused score */
} Scored;

static int cmp_score_desc(const void *a, const void *b) {
    double d = ((const Scored *)b)->score - ((const Scored *)a)->score;
    return (d > 0) - (d < 0);
}

static int cmp_fused_desc(const void *a, const void *b) {
    double d = ((const Scored *)b)->fused - ((const Scored *)a)->fused;
    return (d > 0) - (d < 0);
}

static int count_records(Collection *c) {
    int n = 0;
    Record *r;
    for (r = c->records; r; r = r->next) n++;
    return n;
}

/* Build JSON: {"results":[{"memory_id":..,"content":..,"score":..,"source":..}],"total":N} */
static char *build_results_json(Scored *arr, int n, int top_k, const char *source,
                                int use_fused) {
    JsonBuf jb;
    char tmp[64];
    int i, limit = top_k < n ? top_k : n;
    if (jb_init(&jb) != 0) return NULL;
    if (jb_append(&jb, "{\"results\":[") != 0) goto fail;
    for (i = 0; i < limit; i++) {
        if (i > 0 && jb_append(&jb, ",") != 0) goto fail;
        if (jb_append(&jb, "{\"memory_id\":") != 0) goto fail;
        if (jb_append_json_string(&jb, arr[i].rec->memory_id) != 0) goto fail;
        if (jb_append(&jb, ",\"content\":") != 0) goto fail;
        if (jb_append_json_string(&jb, arr[i].rec->content) != 0) goto fail;
        snprintf(tmp, sizeof(tmp), ",\"score\":%.6f,\"source\":\"%s\"}",
                 use_fused ? arr[i].fused : arr[i].score, source);
        if (jb_append(&jb, tmp) != 0) goto fail;
    }
    snprintf(tmp, sizeof(tmp), "],\"total\":%d}", limit);
    if (jb_append(&jb, tmp) != 0) goto fail;
    return jb.buf;
fail:
    free(jb.buf);
    return NULL;
}

/* Validate search preconditions; returns 0 and sets *pc on success. */
static int check_searchable(Engine *engine, const char *collection_name,
                            Collection **pc) {
    Collection *c;
    if (!engine || !collection_name) return 1;
    c = find_collection(engine, collection_name);
    if (!c) {
        set_last_error(engine, "collection not found");
        return 2;
    }
    if (!c->loaded) {
        set_last_error(engine, "collection not loaded");
        return 3;
    }
    *pc = c;
    return 0;
}

/* ---------------- Lifecycle ---------------- */

KYLIN_EXPORT vector_engine_t vector_engine_create(void) {
    return (vector_engine_t)calloc(1, sizeof(Engine));
}

KYLIN_EXPORT int vector_engine_connect(vector_engine_t engine,
                                       const char *host, int port) {
    Engine *e = (Engine *)engine;
    char msg[256];
    (void)host;
    (void)port;
    if (!e) return 1;
    e->connected = 1;
    snprintf(msg, sizeof(msg), "mock connected to %s:%d",
             host ? host : "", port);
    set_last_error(e, NULL);
    return 0;
}

KYLIN_EXPORT int vector_engine_disconnect(vector_engine_t engine) {
    Engine *e = (Engine *)engine;
    if (!e) return 1;
    e->connected = 0;
    return 0;
}

KYLIN_EXPORT void vector_engine_destroy(vector_engine_t engine) {
    Engine *e = (Engine *)engine;
    Collection *c;
    if (!e) return;
    c = e->collections;
    while (c) {
        Collection *next = c->next;
        free_collection(c);
        c = next;
    }
    free(e->last_error);
    free(e);
}

/* ---------------- Collection management ---------------- */

KYLIN_EXPORT int vector_engine_create_collection(vector_engine_t engine,
                                                 const char *collection_name,
                                                 int dim) {
    Engine *e = (Engine *)engine;
    Collection *c;
    if (!e || !collection_name || dim <= 0) return 1;
    if (find_collection(e, collection_name)) {
        set_last_error(e, "collection already exists");
        return 2;
    }
    c = (Collection *)calloc(1, sizeof(Collection));
    if (!c) return 1;
    c->name = mock_strdup(collection_name);
    if (!c->name) {
        free(c);
        return 1;
    }
    c->dim = dim;
    c->loaded = 0;
    c->next = e->collections;
    e->collections = c;
    return 0;
}

KYLIN_EXPORT int vector_engine_load_collection(vector_engine_t engine,
                                               const char *collection_name) {
    Engine *e = (Engine *)engine;
    Collection *c = find_collection(e, collection_name);
    if (!e || !collection_name) return 1;
    if (!c) {
        set_last_error(e, "collection not found");
        return 2;
    }
    c->loaded = 1;
    return 0;
}

KYLIN_EXPORT int vector_engine_release_collection(vector_engine_t engine,
                                                  const char *collection_name) {
    Engine *e = (Engine *)engine;
    Collection *c = find_collection(e, collection_name);
    if (!e || !collection_name) return 1;
    if (!c) {
        set_last_error(e, "collection not found");
        return 2;
    }
    c->loaded = 0;
    return 0;
}

KYLIN_EXPORT int vector_engine_drop_collection(vector_engine_t engine,
                                               const char *collection_name) {
    Engine *e = (Engine *)engine;
    Collection **link;
    if (!e || !collection_name) return 1;
    link = &e->collections;
    while (*link) {
        if (strcmp((*link)->name, collection_name) == 0) {
            Collection *victim = *link;
            *link = victim->next;
            free_collection(victim);
            return 0;
        }
        link = &(*link)->next;
    }
    set_last_error(e, "collection not found");
    return 2;
}

/* ---------------- Data operations ---------------- */

KYLIN_EXPORT int vector_engine_insert(vector_engine_t engine,
                                      const char *collection_name,
                                      const char *memory_id,
                                      const char *content,
                                      const float *dense_vector,
                                      int dim) {
    Engine *e = (Engine *)engine;
    Collection *c;
    Record *r;
    if (!e || !collection_name || !memory_id || !content || !dense_vector ||
        dim <= 0)
        return 1;
    c = find_collection(e, collection_name);
    if (!c) {
        set_last_error(e, "collection not found");
        return 2;
    }
    if (dim != c->dim) {
        set_last_error(e, "dense vector dim mismatch");
        return 3;
    }
    /* Replace existing record with same memory_id (upsert). */
    vector_engine_delete(engine, collection_name, memory_id);

    r = (Record *)calloc(1, sizeof(Record));
    if (!r) return 1;
    r->memory_id = mock_strdup(memory_id);
    r->content = mock_strdup(content);
    r->dense = (float *)malloc(sizeof(float) * dim);
    if (!r->memory_id || !r->content || !r->dense) {
        free_record(r);
        return 1;
    }
    memcpy(r->dense, dense_vector, sizeof(float) * dim);
    r->dim = dim;
    if (sparse_from_text(content, &r->sp_idx, &r->sp_val, &r->sp_count) != 0) {
        free_record(r);
        set_last_error(e, "out of memory building sparse vector");
        return 1;
    }
    r->next = c->records;
    c->records = r;
    return 0;
}

KYLIN_EXPORT int vector_engine_delete(vector_engine_t engine,
                                      const char *collection_name,
                                      const char *memory_id) {
    Engine *e = (Engine *)engine;
    Collection *c;
    Record **link;
    if (!e || !collection_name || !memory_id) return 1;
    c = find_collection(e, collection_name);
    if (!c) {
        set_last_error(e, "collection not found");
        return 2;
    }
    link = &c->records;
    while (*link) {
        if (strcmp((*link)->memory_id, memory_id) == 0) {
            Record *victim = *link;
            *link = victim->next;
            free_record(victim);
            return 0;
        }
        link = &(*link)->next;
    }
    /* Deleting a missing id is not an error (idempotent). */
    return 0;
}

/* ---------------- Search ---------------- */

KYLIN_EXPORT int vector_engine_hybrid_search(vector_engine_t engine,
                                             const char *collection_name,
                                             const float *dense_vector,
                                             int dim,
                                             const uint32_t *sparse_indices,
                                             const float *sparse_values,
                                             int sparse_count,
                                             int top_k,
                                             char **out_json) {
    Engine *e = (Engine *)engine;
    Collection *c = NULL;
    Scored *dense_rank = NULL, *sparse_rank = NULL;
    int n, i, rc;
    Record *r;
    char *json = NULL;

    if (!e || !out_json) return 1;
    *out_json = NULL;
    rc = check_searchable(e, collection_name, &c);
    if (rc != 0) return rc;
    if (!dense_vector || dim <= 0 || top_k <= 0) {
        set_last_error(e, "invalid search arguments");
        return 1;
    }
    if (dim != c->dim) {
        set_last_error(e, "dense vector dim mismatch");
        return 1;
    }

    n = count_records(c);
    if (n == 0) {
        *out_json = mock_strdup("{\"results\":[],\"total\":0}");
        return *out_json ? 0 : 1;
    }

    /* Dense route: cosine similarity. */
    dense_rank = (Scored *)calloc((size_t)n, sizeof(Scored));
    sparse_rank = (Scored *)calloc((size_t)n, sizeof(Scored));
    if (!dense_rank || !sparse_rank) {
        free(dense_rank);
        free(sparse_rank);
        set_last_error(e, "out of memory");
        return 1;
    }

    i = 0;
    for (r = c->records; r; r = r->next) {
        dense_rank[i].rec = r;
        dense_rank[i].score = cosine(dense_vector, r->dense, dim);
        sparse_rank[i].rec = r;
        sparse_rank[i].score = sparse_dot(
            sparse_indices, sparse_values, sparse_count,
            r->sp_idx, r->sp_val, r->sp_count);
        i++;
    }

    qsort(dense_rank, (size_t)n, sizeof(Scored), cmp_score_desc);
    qsort(sparse_rank, (size_t)n, sizeof(Scored), cmp_score_desc);

    /* RRF fusion: score = sum of 1/(60 + rank) over both routes. */
    for (i = 0; i < n; i++) {
        dense_rank[i].fused = 1.0 / (60.0 + (double)(i + 1));
        sparse_rank[i].fused = 1.0 / (60.0 + (double)(i + 1));
    }
    /* Merge the two routes into one array keyed by record pointer. */
    for (i = 0; i < n; i++) {
        int j;
        for (j = 0; j < n; j++) {
            if (sparse_rank[j].rec == dense_rank[i].rec) {
                dense_rank[i].fused += sparse_rank[j].fused;
                break;
            }
        }
    }

    qsort(dense_rank, (size_t)n, sizeof(Scored), cmp_fused_desc);
    json = build_results_json(dense_rank, n, top_k, "hybrid", 1);
    free(dense_rank);
    free(sparse_rank);
    if (!json) {
        set_last_error(e, "out of memory building result json");
        return 1;
    }
    *out_json = json;
    return 0;
}

KYLIN_EXPORT int vector_engine_dense_search(vector_engine_t engine,
                                            const char *collection_name,
                                            const float *dense_vector,
                                            int dim,
                                            int top_k,
                                            char **out_json) {
    Engine *e = (Engine *)engine;
    Collection *c = NULL;
    Scored *arr = NULL;
    int n, i, rc;
    Record *r;
    char *json = NULL;

    if (!e || !out_json) return 1;
    *out_json = NULL;
    rc = check_searchable(e, collection_name, &c);
    if (rc != 0) return rc;
    if (!dense_vector || dim <= 0 || top_k <= 0) {
        set_last_error(e, "invalid search arguments");
        return 1;
    }
    if (dim != c->dim) {
        set_last_error(e, "dense vector dim mismatch");
        return 1;
    }

    n = count_records(c);
    if (n == 0) {
        *out_json = mock_strdup("{\"results\":[],\"total\":0}");
        return *out_json ? 0 : 1;
    }

    arr = (Scored *)calloc((size_t)n, sizeof(Scored));
    if (!arr) {
        set_last_error(e, "out of memory");
        return 1;
    }
    i = 0;
    for (r = c->records; r; r = r->next) {
        arr[i].rec = r;
        arr[i].score = cosine(dense_vector, r->dense, dim);
        i++;
    }
    qsort(arr, (size_t)n, sizeof(Scored), cmp_score_desc);
    json = build_results_json(arr, n, top_k, "dense", 0);
    free(arr);
    if (!json) {
        set_last_error(e, "out of memory building result json");
        return 1;
    }
    *out_json = json;
    return 0;
}

KYLIN_EXPORT int vector_engine_sparse_search(vector_engine_t engine,
                                             const char *collection_name,
                                             const uint32_t *sparse_indices,
                                             const float *sparse_values,
                                             int sparse_count,
                                             int top_k,
                                             char **out_json) {
    Engine *e = (Engine *)engine;
    Collection *c = NULL;
    Scored *arr = NULL;
    int n, i, rc;
    Record *r;
    char *json = NULL;

    if (!e || !out_json) return 1;
    *out_json = NULL;
    rc = check_searchable(e, collection_name, &c);
    if (rc != 0) return rc;
    if (top_k <= 0 || (sparse_count > 0 && (!sparse_indices || !sparse_values))) {
        set_last_error(e, "invalid search arguments");
        return 1;
    }

    n = count_records(c);
    if (n == 0) {
        *out_json = mock_strdup("{\"results\":[],\"total\":0}");
        return *out_json ? 0 : 1;
    }

    arr = (Scored *)calloc((size_t)n, sizeof(Scored));
    if (!arr) {
        set_last_error(e, "out of memory");
        return 1;
    }
    i = 0;
    for (r = c->records; r; r = r->next) {
        arr[i].rec = r;
        arr[i].score = sparse_dot(sparse_indices, sparse_values, sparse_count,
                                  r->sp_idx, r->sp_val, r->sp_count);
        i++;
    }
    qsort(arr, (size_t)n, sizeof(Scored), cmp_score_desc);
    json = build_results_json(arr, n, top_k, "sparse", 0);
    free(arr);
    if (!json) {
        set_last_error(e, "out of memory building result json");
        return 1;
    }
    *out_json = json;
    return 0;
}

/* ---------------- Helpers ---------------- */

KYLIN_EXPORT void vector_engine_free_buffer(void *buffer) {
    free(buffer);
}

KYLIN_EXPORT int vector_engine_get_last_error(vector_engine_t engine,
                                              char **out_message) {
    Engine *e = (Engine *)engine;
    if (!e || !out_message) return 1;
    *out_message = mock_strdup(e->last_error ? e->last_error : "");
    return *out_message ? 0 : 1;
}
