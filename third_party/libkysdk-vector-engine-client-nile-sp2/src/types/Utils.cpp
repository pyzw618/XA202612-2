// Licensed to the LF AI & Data foundation under one
// or more contributor license agreements. See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership. The ASF licenses this file
// to you under the Apache License, Version 2.0 (the
// "License"); you may not use this file except in compliance
// with the License. You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "types/Utils.h"

namespace std {
std::string to_string(VectorDB::MetricType metric_type) {
    switch (metric_type) {
        case VectorDB::MetricType::L2:
            return "L2";
        case VectorDB::MetricType::IP:
            return "IP";
        case VectorDB::MetricType::COSINE:
            return "COSINE";
        case VectorDB::MetricType::HAMMING:
            return "HAMMING";
        case VectorDB::MetricType::JACCARD:
            return "JACCARD";
        case VectorDB::MetricType::INVALID:
        default:
            return "INVALID";
    }
}

std::string to_string(VectorDB::IndexType index_type) {
    switch (index_type) {
        case VectorDB::IndexType::FLAT:
            return "FLAT";
        case VectorDB::IndexType::IVF_FLAT:
            return "IVF_FLAT";
        case VectorDB::IndexType::IVF_PQ:
            return "IVF_PQ";
        case VectorDB::IndexType::IVF_SQ8:
            return "IVF_SQ8";
        case VectorDB::IndexType::HNSW:
            return "HNSW";
        case VectorDB::IndexType::DISKANN:
            return "DISKANN";
        case VectorDB::IndexType::AUTOINDEX:
            return "AUTOINDEX";
        case VectorDB::IndexType::SCANN:
            return "SCANN";
        case VectorDB::IndexType::GPU_IVF_FLAT:
            return "GPU_IVF_FLAT";
        case VectorDB::IndexType::GPU_IVF_PQ:
            return "GPU_IVF_PQ";
        case VectorDB::IndexType::GPU_BRUTE_FORCE:
            return "GPU_BRUTE_FORCE";
        case VectorDB::IndexType::GPU_CAGRA:
            return "GPU_CAGRA";
        case VectorDB::IndexType::BIN_FLAT:
            return "BIN_FLAT";
        case VectorDB::IndexType::BIN_IVF_FLAT:
            return "BIN_IVF_FLAT";
        case VectorDB::IndexType::TRIE:
            return "Trie";
        case VectorDB::IndexType::STL_SORT:
            return "STL_SORT";
        case VectorDB::IndexType::INVERTED:
            return "INVERTED";
        case VectorDB::IndexType::SPARSE_INVERTED_INDEX:
            return "SPARSE_INVERTED_INDEX";
        case VectorDB::IndexType::SPARSE_WAND:
            return "SPARSE_WAND";
        default:
            return "INVALID";
    }
}
}  // namespace std

namespace VectorDB {
std::string Base64Encode(const std::string& val) {
    const char* base64_chars = {
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789"
        "+/"};

    auto len = val.size();
    auto len_encoded = (len + 2) / 3 * 4;
    std::string ret;
    ret.reserve(len_encoded);

    size_t pos = 0;

    while (pos < len) {
        ret.push_back(base64_chars[(val[pos + 0] & 0xfc) >> 2]);

        if (pos + 1 < len) {
            ret.push_back(base64_chars[((val[pos + 0] & 0x03) << 4) + ((val[pos + 1] & 0xf0) >> 4)]);

            if (pos + 2 < len) {
                ret.push_back(base64_chars[((val[pos + 1] & 0x0f) << 2) + ((val[pos + 2] & 0xc0) >> 6)]);
                ret.push_back(base64_chars[val[pos + 2] & 0x3f]);
            } else {
                ret.push_back(base64_chars[(val[pos + 1] & 0x0f) << 2]);
                ret.push_back('=');
            }
        } else {
            ret.push_back(base64_chars[(val[pos + 0] & 0x03) << 4]);
            ret.push_back('=');
            ret.push_back('=');
        }

        pos += 3;
    }

    return ret;
}

bool IsSmallerDistanceHigherSimilarityMetricType(MetricType type) {
    return type == MetricType::L2 || type == MetricType::JACCARD || type == MetricType::HAMMING;
}

bool IsLargerDistanceHigherSimilarityMetricType(MetricType type) {
    return type == MetricType::IP || type == MetricType::COSINE;
}
}  // namespace VectorDB
