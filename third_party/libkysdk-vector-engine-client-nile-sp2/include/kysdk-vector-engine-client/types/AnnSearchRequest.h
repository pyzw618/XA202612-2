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

#include <map>
#include <nlohmann/json.hpp>
#include <set>
#include <string>
#include <vector>

#include "FieldData.h"

namespace VectorDB {

class AnnSearchRequest {
public:
    AnnSearchRequest(std::string anns_field, int limit, std::map<std::string, std::string> param = {},
                     std::string expr = "")
        : anns_field_(std::move(anns_field)), limit_(limit), param_(std::move(param)), expr_(std::move(expr)) {}

    const std::string& AnnsField() const;
    const std::map<std::string, std::string>& Param() const;
    int Limit() const;
    const std::string& Expr() const;
    Status SetExpression(const std::string& expression);

    FieldDataPtr TargetVectors() const;

    Status AddTargetVector(std::string field_name, const std::string& vector);

    Status AddTargetVector(std::string field_name, const std::vector<uint8_t>& vector);

    Status AddTargetVector(std::string field_name, std::string&& vector);

    Status AddTargetVector(std::string field_name, const FloatVecFieldData::ElementT& vector);

    Status AddTargetVector(std::string field_name, FloatVecFieldData::ElementT&& vector);

    Status AddTargetVector(const std::string& field_name, const SparseFloatVecFieldData::ElementT& vector);

    Status AddTargetVector(const std::string& field_name, SparseFloatVecFieldData::ElementT&& vector);

private:
    std::string anns_field_;
    std::map<std::string, std::string> param_;
    int limit_;
    std::string expr_;

    BinaryVecFieldDataPtr binary_vectors_;
    FloatVecFieldDataPtr float_vectors_;
    SparseFloatVecFieldDataPtr sparse_vectors_;
};

}  // namespace VectorDB
