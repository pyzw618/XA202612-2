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

#include "types/FieldData.h"

#include <algorithm>
#include <iostream>

namespace VectorDB {

namespace {

template <DataType Dt>
struct DataTypeTraits {
    static const bool is_vector = false;
};

template <>
struct DataTypeTraits<DataType::BINARY_VECTOR> {
    static const bool is_vector = true;
};

template <>
struct DataTypeTraits<DataType::FLOAT_VECTOR> {
    static const bool is_vector = true;
};

template <>
struct DataTypeTraits<DataType::SPARSE_FLOAT_VECTOR> {
    // sparse vector cannot check array size, tmp set is_vector false
    static const bool is_vector = false;
};

template <typename T, DataType Dt, std::enable_if_t<!DataTypeTraits<Dt>::is_vector, bool> = true>
StatusCode AddElement(const T& element, std::vector<T>& array) {
    array.push_back(element);
    return StatusCode::OK;
}

template <typename T, DataType Dt, std::enable_if_t<DataTypeTraits<Dt>::is_vector, bool> = true>
StatusCode AddElement(const T& element, std::vector<T>& array) {
    if (element.empty()) {
        return StatusCode::VECTOR_IS_EMPTY;
    }

    if (!array.empty() && element.size() != array.at(0).size()) {
        return StatusCode::DIMENSION_NOT_EQUAL;
    }

    array.emplace_back(element);
    return StatusCode::OK;
}

}  // namespace

const std::string& Field::Name() const { return name_; }

DataType Field::Type() const { return data_type_; }

DataType Field::ElementType() const { return element_type_; }

Field::Field(std::string name, DataType data_type) : name_(std::move(name)), data_type_(data_type) {}

template <typename T, DataType Dt>
FieldData<T, Dt>::FieldData() : Field("", Dt) {}

template <typename T, DataType Dt>
FieldData<T, Dt>::FieldData(std::string name) : Field(std::move(name), Dt) {}

template <typename T, DataType Dt>
FieldData<T, Dt>::FieldData(std::string name, const std::vector<T>& data) : Field(std::move(name), Dt), data_(data) {}

template <typename T, DataType Dt>
FieldData<T, Dt>::FieldData(std::string name, std::vector<T>&& data)
    : Field(std::move(name), Dt), data_(std::move(data)) {}

template <typename T, DataType Dt>
StatusCode FieldData<T, Dt>::Add(const T& element) {
    return AddElement<T, Dt>(element, data_);
}

template <typename T, DataType Dt>
StatusCode FieldData<T, Dt>::Add(T&& element) {
    return AddElement<T, Dt>(std::move(element), data_);
}

template <typename T, DataType Dt>
size_t FieldData<T, Dt>::Count() const {
    return data_.size();
}

template <typename T, DataType Dt>
const std::vector<T>& FieldData<T, Dt>::Data() const {
    return data_;
}

template <typename T, DataType Dt>
std::vector<T>& FieldData<T, Dt>::Data() {
    return data_;
}

// ArrayFieldData class
template <typename T, DataType Et>
ArrayFieldData<T, Et>::ArrayFieldData() : FieldData<ArrayFieldData::ElementT, DataType::ARRAY>() {
    this->element_type_ = Et;
}

template <typename T, DataType Et>
ArrayFieldData<T, Et>::ArrayFieldData(std::string name)
    : FieldData<ArrayFieldData::ElementT, DataType::ARRAY>(std::move(name)) {
    this->element_type_ = Et;
}

template <typename T, DataType Et>
ArrayFieldData<T, Et>::ArrayFieldData(std::string name, const std::vector<ArrayFieldData::ElementT>& data)
    : FieldData<ArrayFieldData::ElementT, DataType::ARRAY>(std::move(name), data) {
    this->element_type_ = Et;
}

template <typename T, DataType Et>
ArrayFieldData<T, Et>::ArrayFieldData(std::string name, std::vector<ArrayFieldData::ElementT>&& data)
    : FieldData<ArrayFieldData::ElementT, DataType::ARRAY>(std::move(name), data) {
    this->element_type_ = Et;
}

template <typename T, DataType Et>
StatusCode ArrayFieldData<T, Et>::Add(const ArrayFieldData::ElementT& element) {
    this->data_.emplace_back(element);
    return StatusCode::OK;
}

template <typename T, DataType Et>
StatusCode ArrayFieldData<T, Et>::Add(ArrayFieldData::ElementT&& element) {
    this->data_.emplace_back(element);
    return StatusCode::OK;
}

BinaryVecFieldData::BinaryVecFieldData() : FieldData<std::string, DataType::BINARY_VECTOR>() {}

BinaryVecFieldData::BinaryVecFieldData(std::string name)
    : FieldData<std::string, DataType::BINARY_VECTOR>(std::move(name)) {}

BinaryVecFieldData::BinaryVecFieldData(std::string name, const std::vector<std::string>& data)
    : FieldData<std::string, DataType::BINARY_VECTOR>(std::move(name), data) {}

BinaryVecFieldData::BinaryVecFieldData(std::string name, std::vector<std::string>&& data)
    : FieldData<std::string, DataType::BINARY_VECTOR>(std::move(name), std::move(data)) {}

BinaryVecFieldData::BinaryVecFieldData(std::string name, const std::vector<std::vector<uint8_t>>& data)
    : FieldData<std::string, DataType::BINARY_VECTOR>(std::move(name), CreateBinaryStrings(data)) {}

const std::vector<std::string>& BinaryVecFieldData::Data() const { return data_; }

std::vector<std::string>& BinaryVecFieldData::Data() { return data_; }

std::vector<std::vector<uint8_t>> BinaryVecFieldData::DataAsUnsignedChars() const {
    std::vector<std::vector<uint8_t>> ret;
    ret.reserve(data_.size());
    for (const auto& item : data_) {
        ret.emplace_back(item.begin(), item.end());
    }
    return ret;
}

StatusCode BinaryVecFieldData::Add(const std::string& element) {
    return AddElement<std::string, DataType::BINARY_VECTOR>(element, data_);
}

StatusCode BinaryVecFieldData::Add(std::string&& element) {
    return AddElement<std::string, DataType::BINARY_VECTOR>(element, data_);
}

StatusCode BinaryVecFieldData::Add(const std::vector<uint8_t>& element) {
    return Add(std::string{element.begin(), element.end()});
}

std::vector<std::string> BinaryVecFieldData::CreateBinaryStrings(const std::vector<std::vector<uint8_t>>& data) {
    std::vector<std::string> ret;
    ret.reserve(data.size());
    for (const auto& item : data) {
        ret.emplace_back(item.begin(), item.end());
    }
    return ret;
}

std::string BinaryVecFieldData::CreateBinaryString(const std::vector<uint8_t>& data) {
    return std::string{data.begin(), data.end()};
}

SparseFloatVecFieldData::SparseFloatVecFieldData(const std::string& name)
    : FieldData<std::vector<std::pair<uint32_t, float>>, DataType::SPARSE_FLOAT_VECTOR>(name) {}

SparseFloatVecFieldData::SparseFloatVecFieldData(const std::string& name,
                                                 const std::vector<std::vector<std::pair<uint32_t, float>>>& data)
    : FieldData<std::vector<std::pair<uint32_t, float>>, DataType::SPARSE_FLOAT_VECTOR>(name, data) {}

StatusCode SparseFloatVecFieldData::Add(const std::vector<std::pair<uint32_t, float>>& element) {
    return AddElement<std::vector<std::pair<uint32_t, float>>, DataType::SPARSE_FLOAT_VECTOR>(element, data_);
}

StatusCode SparseFloatVecFieldData::Add(std::vector<std::pair<uint32_t, float>>&& element) {
    return AddElement<std::vector<std::pair<uint32_t, float>>, DataType::SPARSE_FLOAT_VECTOR>(element, data_);
}

const std::vector<std::vector<std::pair<uint32_t, float>>>& SparseFloatVecFieldData::Data() const { return data_; }

std::vector<std::vector<std::pair<uint32_t, float>>>& SparseFloatVecFieldData::Data() { return data_; }

std::string SparseFloatVecFieldData::SortAndSerialize(std::vector<std::pair<uint32_t, float>>& data) {
    // 按照position排序，以免填加的元素未排序
    std::sort(data.begin(), data.end(), [](const auto& a, const auto& b) { return a.first < b.first; });

    std::vector<uint8_t> bytes;
    bytes.resize(8 * data.size());

    for (int i = 0; i < data.size(); i++) {
        uint32_t pos = data[i].first;
        bytes[i * 8] = pos & 0xFF;
        bytes[i * 8 + 1] = (pos >> 8) & 0xFF;
        bytes[i * 8 + 2] = (pos >> 16) & 0xFF;
        bytes[i * 8 + 3] = (pos >> 24) & 0xFF;

        uint32_t valueBits;
        std::memcpy(&valueBits, &(data[i].second), sizeof(valueBits));
        bytes[i * 8 + 4] = valueBits & 0xFF;
        bytes[i * 8 + 5] = (valueBits >> 8) & 0xFF;
        bytes[i * 8 + 6] = (valueBits >> 16) & 0xFF;
        bytes[i * 8 + 7] = (valueBits >> 24) & 0xFF;
    }
    return std::string{bytes.begin(), bytes.end()};
}

std::vector<std::pair<uint32_t, float>> SparseFloatVecFieldData::Deserialize(const std::string& data) {
    std::vector<uint8_t> bytes;
    std::transform(data.begin(), data.end(), std::back_inserter(bytes), [](char c) { return static_cast<uint8_t>(c); });

    if (bytes.size() % 8 != 0) {
        std::cerr << "SparseFloatVecFieldData::Deserialize input data length is wrong." << std::endl;
        return std::vector<std::pair<uint32_t, float>>();
    }

    std::vector<std::pair<uint32_t, float>> result;
    auto len = bytes.size() / 8;
    result.reserve(len);

    for (int i = 0; i < len; i++) {
        uint32_t pos = static_cast<uint32_t>(bytes[i * 8 + 3] << 24) | static_cast<uint32_t>(bytes[i * 8 + 2] << 16) |
                       static_cast<uint32_t>(bytes[i * 8 + 1] << 8) | static_cast<uint32_t>(bytes[i * 8]);
        uint32_t valueBit = static_cast<uint32_t>(bytes[i * 8 + 7] << 24) |
                            static_cast<uint32_t>(bytes[i * 8 + 6] << 16) |
                            static_cast<uint32_t>(bytes[i * 8 + 5] << 8) | static_cast<uint32_t>(bytes[i * 8 + 4]);
        float value;
        std::memcpy(&value, &valueBit, sizeof(valueBit));
        result.emplace_back(std::make_pair(pos, value));
    }
    return result;
}

// explicit declare FieldData
template class FieldData<bool, DataType::BOOL>;
template class FieldData<int8_t, DataType::INT8>;
template class FieldData<int16_t, DataType::INT16>;
template class FieldData<int32_t, DataType::INT32>;
template class FieldData<int64_t, DataType::INT64>;
template class FieldData<float, DataType::FLOAT>;
template class FieldData<double, DataType::DOUBLE>;
template class FieldData<std::string, DataType::VARCHAR>;
template class FieldData<nlohmann::json, DataType::JSON>;
template class FieldData<std::string, DataType::BINARY_VECTOR>;
template class FieldData<std::vector<float>, DataType::FLOAT_VECTOR>;
template class FieldData<std::vector<std::pair<uint32_t, float>>, DataType::SPARSE_FLOAT_VECTOR>;

template class ArrayFieldData<bool, DataType::BOOL>;
template class ArrayFieldData<int8_t, DataType::INT8>;
template class ArrayFieldData<int16_t, DataType::INT16>;
template class ArrayFieldData<int32_t, DataType::INT32>;
template class ArrayFieldData<int64_t, DataType::INT64>;
template class ArrayFieldData<float, DataType::FLOAT>;
template class ArrayFieldData<double, DataType::DOUBLE>;
template class ArrayFieldData<std::string, DataType::VARCHAR>;
}  // namespace VectorDB
