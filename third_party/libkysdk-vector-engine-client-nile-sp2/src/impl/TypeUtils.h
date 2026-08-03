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

#pragma once

#include "milvus.pb.h"
#include "types/CollectionSchema.h"
#include "types/FieldData.h"
#include "types/IDArray.h"
#include "types/IndexState.h"
#include "types/IndexType.h"
#include "types/MetricType.h"

namespace VectorDB {
using namespace milvus;

bool operator==(const proto::schema::FieldData& lhs, const BoolFieldData& rhs);

bool operator==(const proto::schema::FieldData& lhs, const Int8FieldData& rhs);

bool operator==(const proto::schema::FieldData& lhs, const Int16FieldData& rhs);

bool operator==(const proto::schema::FieldData& lhs, const Int32FieldData& rhs);

bool operator==(const proto::schema::FieldData& lhs, const Int64FieldData& rhs);

bool operator==(const proto::schema::FieldData& lhs, const FloatFieldData& rhs);

bool operator==(const proto::schema::FieldData& lhs, const DoubleFieldData& rhs);

bool operator==(const proto::schema::FieldData& lhs, const VarCharFieldData& rhs);

bool operator==(const proto::schema::FieldData& lhs, const JsonFieldData& rhs);

bool operator==(const proto::schema::FieldData& lhs, const BinaryVecFieldData& rhs);

bool operator==(const proto::schema::FieldData& lhs, const FloatVecFieldData& rhs);

bool operator==(const proto::schema::FieldData& lhs, const SparseFloatVecFieldData& rhs);

bool operator==(const proto::schema::FieldData& lhs, const Field& rhs);

proto::schema::DataType DataTypeCast(DataType type);

DataType DataTypeCast(proto::schema::DataType type);

MetricType MetricTypeCast(const std::string& type);

IndexType IndexTypeCast(const std::string& type);

proto::schema::FieldData CreateProtoFieldData(const Field& field);

template <typename T, typename VectorData>
std::vector<T> BuildFieldDataVectors(int64_t dim_bytes, const VectorData& vector_data, size_t offset, size_t count) {
    std::vector<T> data{};
    data.reserve(count * dim_bytes);
    auto cursor = vector_data.begin();
    std::advance(cursor, offset * dim_bytes);
    auto end = cursor;
    std::advance(end, count * dim_bytes);
    while (cursor != end) {
        T item{};
        item.reserve(dim_bytes);
        std::copy_n(cursor, dim_bytes, std::back_inserter(item));
        data.emplace_back(std::move(item));
        std::advance(cursor, dim_bytes);
    }
    return data;
}

template <typename T, typename VectorData>
std::vector<T> BuildFieldDataVectors(int64_t dim_bytes, const VectorData& vector_data) {
    return BuildFieldDataVectors<T>(dim_bytes, vector_data, 0, vector_data.size() / dim_bytes);
}

template <typename VectorData>
std::vector<std::vector<std::pair<uint32_t, float>>> BuildSparseFieldDataVectors(const VectorData& vector_data,
                                                                                 size_t offset, size_t count) {
    std::vector<std::vector<std::pair<uint32_t, float>>> result;
    result.reserve(count);
    auto cursor = vector_data.begin();
    std::advance(cursor, offset);
    auto end = cursor;
    std::advance(end, count);
    while (cursor != end) {
        result.emplace_back(SparseFloatVecFieldData::Deserialize(*cursor));
        std::advance(cursor, 1);
    }
    return result;
}

template <typename VectorData>
std::vector<std::vector<std::pair<uint32_t, float>>> BuildSparseFieldDataVectors(const VectorData& vector_data) {
    return BuildSparseFieldDataVectors(vector_data, 0, vector_data.size());
}

template <typename T, typename ScalarData>
std::vector<T> BuildFieldDataScalars(const ScalarData& scalar_data, size_t offset, size_t count) {
    std::vector<T> data{};
    data.reserve(count);
    auto begin = scalar_data.begin();
    std::advance(begin, offset);
    auto end = begin;
    std::advance(end, count);
    std::copy(begin, end, std::back_inserter(data));
    return data;
}

template <typename T, typename ScalarData>
std::vector<T> BuildFieldDataScalars(const ScalarData& scalar_data) {
    return BuildFieldDataScalars<T>(scalar_data, 0, scalar_data.size());
}

FieldDataPtr CreateMilvusFieldData(const proto::schema::FieldData& field_data, size_t offset, size_t count);

FieldDataPtr CreateMilvusFieldData(const proto::schema::FieldData& field_data);

IDArray CreateIDArray(const proto::schema::IDs& ids);

IDArray CreateIDArray(const proto::schema::IDs& ids, size_t offset, size_t size);

void ConvertFieldSchema(const proto::schema::FieldSchema& proto_schema, FieldSchema& schema);

void ConvertCollectionSchema(const proto::schema::CollectionSchema& proto_schema, CollectionSchema& schema);

void ConvertFieldSchema(const FieldSchema& schema, proto::schema::FieldSchema& proto_schema);

void ConvertCollectionSchema(const CollectionSchema& schema, proto::schema::CollectionSchema& proto_schema);

IndexStateCode IndexStateCast(proto::common::IndexState state);

bool IsVectorType(DataType type);
}  // namespace VectorDB
