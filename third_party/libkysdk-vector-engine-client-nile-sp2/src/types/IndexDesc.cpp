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

#include "types/IndexDesc.h"

#include <nlohmann/json.hpp>

#include "types/Utils.h"

namespace VectorDB {

namespace {

struct Validation {
    IndexType index_type;
    std::string param;
    int64_t min;
    int64_t max;
    bool required;

    Status Validate(const IndexDesc& data, std::unordered_map<std::string, int64_t> params) const {
        if (data.IndexType() == index_type) {
            auto it = params.find(param);
            // required and not found
            if (it == params.end() && required) {
                return {StatusCode::INVALID_AGUMENT, "missing required parameter: " + param};
            }
            // found, check value
            if (it != params.end()) {
                auto value = it->second;
                if (value < min || value > max) {
                    return {StatusCode::INVALID_AGUMENT, "invalid value: " + param + "=" + std::to_string(value) +
                                                             ", requires [" + std::to_string(min) + ", " +
                                                             std::to_string(max) + "]"};
                }
            }
        }
        return Status::OK();
    }
};

Status validate_index_and_metric(const MetricType metric_type, const IndexType index_type) {
    if ((metric_type == MetricType::IP || metric_type == MetricType::L2 || metric_type == MetricType::COSINE) &&
        (index_type == IndexType::FLAT || index_type == IndexType::SPARSE_INVERTED_INDEX ||
         index_type == IndexType::SPARSE_WAND)) {
        return Status::OK();
    }

    if ((metric_type == MetricType::JACCARD || metric_type == MetricType::HAMMING) &&
        (index_type == IndexType::BIN_FLAT || index_type == IndexType::BIN_IVF_FLAT)) {
        return Status::OK();
    }

    return {StatusCode::INVALID_AGUMENT, "Index type and metric type not match, index " + std::to_string(index_type) +
                                             " with metric " + std::to_string(metric_type)};
}

Status validate_params(const IndexDesc& data, const std::unordered_map<std::string, int64_t>& params) {
    auto status = Status::OK();
    auto validations = {
        Validation{IndexType::IVF_FLAT, "nlist", 1, 65536, true},
        Validation{IndexType::IVF_SQ8, "nlist", 1, 65536, true},

        Validation{IndexType::IVF_PQ, "nlist", 1, 65536, true},
        Validation{IndexType::IVF_PQ, "m", 1, 65536, true},  // TODO: m requires mod(dim) == 0
        Validation{IndexType::IVF_PQ, "nbits", 1, 16, false},

        Validation{IndexType::HNSW, "M", 4, 64, true},
        Validation{IndexType::HNSW, "efConstruction", 8, 512, true},
    };

    for (const auto& validation : validations) {
        status = validation.Validate(data, params);
        if (!status.IsOk()) {
            return status;
        }
    }
    return status;
}
}  // namespace

IndexDesc::IndexDesc() = default;

IndexDesc::IndexDesc(std::string field_name, std::string index_name, VectorDB::IndexType index_type,
                     VectorDB::MetricType metric_type)
    : field_name_(std::move(field_name)),
      index_name_(std::move(index_name)),
      index_type_(index_type),
      metric_type_(metric_type) {}

const std::string& IndexDesc::FieldName() const { return field_name_; }

Status IndexDesc::SetFieldName(std::string field_name) {
    field_name_ = std::move(field_name);
    return Status::OK();
}

const std::string& IndexDesc::IndexName() const { return index_name_; }

Status IndexDesc::SetIndexName(std::string index_name) {
    index_name_ = std::move(index_name);
    return Status::OK();
}

int64_t IndexDesc::IndexId() const { return index_id_; }

Status IndexDesc::SetIndexId(int64_t index_id) {
    index_id_ = index_id;
    return Status::OK();
}

VectorDB::MetricType IndexDesc::MetricType() const { return metric_type_; }

Status IndexDesc::SetMetricType(VectorDB::MetricType metric_type) {
    metric_type_ = metric_type;
    return Status::OK();
}

VectorDB::IndexType IndexDesc::IndexType() const { return index_type_; }

Status IndexDesc::SetIndexType(VectorDB::IndexType index_type) {
    index_type_ = index_type;
    return Status::OK();
}

std::string IndexDesc::ExtraParams() const { return ::nlohmann::json(extra_params_).dump(); }

Status IndexDesc::AddExtraParam(std::string key, int64_t value) {
    extra_params_[std::move(key)] = value;
    return Status::OK();
}

Status IndexDesc::ExtraParamsFromJson(const std::string& json) {
    try {
        auto obj = ::nlohmann::json::parse(json);
        extra_params_ = obj.get<std::unordered_map<std::string, int64_t>>();
    } catch (const ::nlohmann::json::exception& e) {
        return {StatusCode::JSON_PARSE_ERROR, e.what()};
    }
    return Status::OK();
}

Status IndexDesc::Validate() const {
    auto status = validate_index_and_metric(metric_type_, index_type_);
    if (status.IsOk()) {
        status = validate_params(*this, extra_params_);
    }
    return status;
}

Status IndexDesc::SetStateCode(const IndexStateCode& code) {
    state_code_ = code;
    return Status::OK();
}

VectorDB::IndexStateCode IndexDesc::StateCode() const { return state_code_; }

Status IndexDesc::SetFailReason(const std::string& reason) {
    failed_reason_ = reason;
    return Status::OK();
}

std::string IndexDesc::FailReason() const { return failed_reason_; }

Status IndexDesc::SetIndexedRows(int64_t rows) {
    indexed_rows_ = rows;
    return Status::OK();
}

int64_t IndexDesc::IndexedRows() const { return indexed_rows_; }

Status IndexDesc::SetTotalRows(int64_t rows) {
    total_rows_ = rows;
    return Status::OK();
}

int64_t IndexDesc::TotalRows() const { return total_rows_; }

Status IndexDesc::SetPendingRows(int64_t rows) {
    pending_rows_ = rows;
    return Status::OK();
}

int64_t IndexDesc::PendingRows() const { return pending_rows_; }
}  // namespace VectorDB
