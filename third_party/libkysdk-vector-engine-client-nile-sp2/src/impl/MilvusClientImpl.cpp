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

#include "MilvusClientImpl.h"

#include <algorithm>
#include <nlohmann/json.hpp>

#include "TypeUtils.h"
#include "common.pb.h"
#include "milvus.pb.h"
#include "schema.pb.h"
#include "types/Utils.h"

namespace VectorDB {
using namespace milvus;

MilvusClientImpl::~MilvusClientImpl() { Disconnect(); }

Status MilvusClientImpl::Connect(const ConnectParam& param) {
    if (connection_ != nullptr) {
        connection_->Disconnect();
    }

    connection_ = std::make_shared<MilvusConnection>(param);
    int retryTime = 0;
    Status status = connection_->Connect();
    while (status.Code() == StatusCode::NOT_CONNECTED && retryTime <= RETRY_TIME) {
        if (retryTime == RETRY_TIME) {
            std::cerr << "ERROR connect milvus retry failed, code: " << static_cast<int>(status.Code())
                      << ", msg: " << status.Message() << std::endl;
            return status;
        }
        std::cout << "WARN connect milvus failed, code: " << static_cast<int>(status.Code())
                  << ", msg: " << status.Message() << ", retry: " << retryTime << std::endl;

        sleep(1);
        retryTime++;
        status = connection_->Connect();
    }
    return status;
}

Status MilvusClientImpl::Disconnect() {
    if (connection_ != nullptr) {
        return connection_->Disconnect();
    }

    return Status::OK();
}

Status MilvusClientImpl::LoadDBFile(const std::string& db_file, bool encrypt, const std::string& key) {
    auto validate = [&db_file, &encrypt, &key] {
        return (db_file.empty() || (encrypt && key.empty()))
                   ? Status{StatusCode::INVALID_AGUMENT, "LoadDBFile input param wrong."}
                   : Status::OK();
    };

    auto pre = [&db_file, &encrypt, &key]() {
        proto::milvus::LoadDBFileRequest rpc_request;
        rpc_request.set_db_file(db_file);
        rpc_request.set_encrypt(encrypt);
        rpc_request.set_key(key);
        return rpc_request;
    };

    return apiHandler<proto::milvus::LoadDBFileRequest, proto::common::Status>(validate, pre,
                                                                               &MilvusConnection::LoadDBFile);
}

Status MilvusClientImpl::CreateCollection(const CollectionSchema& schema, const IndexDesc& index_desc) {
    // create collection
    auto status = CreateCollection(schema);
    if (!status.IsOk()) {
        return status;
    }

    // create index
    status = CreateIndex(schema.Name(), index_desc);
    if (!status.IsOk()) {
        return status;
    }
    return Status();
}

Status MilvusClientImpl::CreateCollection(const std::string& collection_name, int dim, bool auto_id,
                                          bool enable_dynamic_field) {
    // create collection schema
    CollectionSchema schema(collection_name, "default schema", enable_dynamic_field);
    schema.AddField({DEFAULT_ID_FIELD_NAME, DataType::INT64, "user id", true, auto_id});
    schema.AddField(FieldSchema(DEFAULT_VECTOR_FIELD_NAME, DataType::FLOAT_VECTOR, "vector").WithDimension(dim));

    auto status = CreateCollection(schema);
    if (!status.IsOk()) {
        return status;
    }

    // create index
    IndexDesc desc(DEFAULT_VECTOR_FIELD_NAME, "vector_index");
    status = CreateIndex(schema.Name(), desc);
    if (!status.IsOk()) {
        return status;
    }
    return Status();
}

Status MilvusClientImpl::CreateCollection(const CollectionSchema& schema) {
    auto pre = [&schema]() {
        proto::milvus::CreateCollectionRequest rpc_request;
        rpc_request.set_collection_name(schema.Name());

        proto::schema::CollectionSchema rpc_collection;
        rpc_collection.set_name(schema.Name());
        rpc_collection.set_description(schema.Description());
        rpc_collection.set_enable_dynamic_field(schema.EnableDynamicField());

        for (auto& field : schema.Fields()) {
            proto::schema::FieldSchema* rpc_field = rpc_collection.add_fields();
            rpc_field->set_name(field.Name());
            rpc_field->set_description(field.Description());
            rpc_field->set_data_type(static_cast<proto::schema::DataType>(field.FieldDataType()));
            rpc_field->set_is_primary_key(field.IsPrimaryKey());
            rpc_field->set_autoid(field.AutoID());

            if (field.FieldDataType() == DataType::ARRAY) {
                rpc_field->set_element_type(static_cast<proto::schema::DataType>(field.ElementType()));
            }

            for (auto& pair : field.TypeParams()) {
                proto::common::KeyValuePair* kv = rpc_field->add_type_params();
                kv->set_key(pair.first);
                kv->set_value(pair.second);
            }
        }
        // std::cout << "rpc collection: " << rpc_collection.DebugString() << std::endl;
        std::string binary;
        rpc_collection.SerializeToString(&binary);
        rpc_request.set_schema(binary);
        return rpc_request;
    };

    return apiHandler<proto::milvus::CreateCollectionRequest, proto::common::Status>(
        pre, &MilvusConnection::CreateCollection);
}

Status MilvusClientImpl::HasCollection(const std::string& collection_name, bool& has) {
    auto validate = [&collection_name] {
        return collection_name.empty() ? Status{StatusCode::INVALID_AGUMENT, "collection_name cannot be empty!"}
                                       : Status::OK();
    };

    auto pre = [&collection_name]() {
        proto::milvus::HasCollectionRequest rpc_request;
        rpc_request.set_collection_name(collection_name);
        rpc_request.set_time_stamp(0);
        return rpc_request;
    };

    auto post = [&has](const proto::milvus::BoolResponse& response) { has = response.value(); };

    return apiHandler<proto::milvus::HasCollectionRequest, proto::milvus::BoolResponse>(
        validate, pre, &MilvusConnection::HasCollection, post);
}

Status MilvusClientImpl::DropCollection(const std::string& collection_name) {
    auto validate = [&collection_name] {
        return collection_name.empty() ? Status{StatusCode::INVALID_AGUMENT, "collection_name cannot be empty!"}
                                       : Status::OK();
    };

    auto pre = [&collection_name]() {
        proto::milvus::DropCollectionRequest rpc_request;
        rpc_request.set_collection_name(collection_name);
        return rpc_request;
    };

    return apiHandler<proto::milvus::DropCollectionRequest, proto::common::Status>(validate, pre,
                                                                                   &MilvusConnection::DropCollection);
}

Status MilvusClientImpl::LoadCollection(const std::string& collection_name) {
    auto validate = [&collection_name] {
        return collection_name.empty() ? Status{StatusCode::INVALID_AGUMENT, "collection_name cannot be empty!"}
                                       : Status::OK();
    };

    auto pre = [&collection_name]() {
        proto::milvus::LoadCollectionRequest rpc_request;
        rpc_request.set_collection_name(collection_name);
        return rpc_request;
    };

    // todo 要不要查询加载进度
    return apiHandler<proto::milvus::LoadCollectionRequest, proto::common::Status>(validate, pre,
                                                                                   &MilvusConnection::LoadCollection);
}

Status MilvusClientImpl::ReleaseCollection(const std::string& collection_name) {
    auto validate = [&collection_name] {
        return collection_name.empty() ? Status{StatusCode::INVALID_AGUMENT, "collection_name cannot be empty!"}
                                       : Status::OK();
    };

    auto pre = [&collection_name]() {
        proto::milvus::ReleaseCollectionRequest rpc_request;
        rpc_request.set_collection_name(collection_name);
        return rpc_request;
    };

    return apiHandler<proto::milvus::ReleaseCollectionRequest, proto::common::Status>(
        validate, pre, &MilvusConnection::ReleaseCollection);
}

Status MilvusClientImpl::DescribeCollection(const std::string& collection_name, CollectionDesc& collection_desc) {
    auto validate = [&collection_name] {
        return collection_name.empty() ? Status{StatusCode::INVALID_AGUMENT, "collection_name cannot be empty!"}
                                       : Status::OK();
    };

    auto pre = [&collection_name]() {
        proto::milvus::DescribeCollectionRequest rpc_request;
        rpc_request.set_collection_name(collection_name);
        return rpc_request;
    };

    auto post = [&collection_desc](const proto::milvus::DescribeCollectionResponse& response) {
        CollectionSchema schema;
        ConvertCollectionSchema(response.schema(), schema);
        collection_desc.SetSchema(std::move(schema));
        collection_desc.SetID(response.collectionid());

        std::vector<std::string> aliases;
        aliases.reserve(response.aliases_size());
        aliases.insert(aliases.end(), response.aliases().begin(), response.aliases().end());

        collection_desc.SetAlias(std::move(aliases));
        collection_desc.SetCreatedTime(response.created_timestamp());
    };

    return apiHandler<proto::milvus::DescribeCollectionRequest, proto::milvus::DescribeCollectionResponse>(
        validate, pre, &MilvusConnection::DescribeCollection, post);
}

Status MilvusClientImpl::CreateIndex(const std::string& collection_name, const IndexDesc& index_desc) {
    auto validate = [&index_desc] { return index_desc.Validate(); };

    auto pre = [&collection_name, &index_desc]() {
        proto::milvus::CreateIndexRequest rpc_request;
        rpc_request.set_collection_name(collection_name);
        rpc_request.set_field_name(index_desc.FieldName());
        rpc_request.set_index_name(index_desc.IndexName());

        auto kv_pair = rpc_request.add_extra_params();
        kv_pair->set_key(KeyIndexType());
        kv_pair->set_value(std::to_string(index_desc.IndexType()));

        kv_pair = rpc_request.add_extra_params();
        kv_pair->set_key(KeyMetricType());
        kv_pair->set_value(std::to_string(index_desc.MetricType()));

        kv_pair = rpc_request.add_extra_params();
        kv_pair->set_key(KeyParams());
        kv_pair->set_value(index_desc.ExtraParams());

        return rpc_request;
    };

    // todo 要不要查询加载进度
    return apiHandler<proto::milvus::CreateIndexRequest, proto::common::Status>(validate, pre,
                                                                                &MilvusConnection::CreateIndex);
}

Status MilvusClientImpl::DropIndex(const std::string& collection_name, const std::string& index_name) {
    auto validate = [&collection_name, &index_name] {
        return (collection_name.empty() || index_name.empty())
                   ? Status{StatusCode::INVALID_AGUMENT, "collection_name and index_name cannot be empty!"}
                   : Status::OK();
    };

    auto pre = [&collection_name, &index_name]() {
        proto::milvus::DropIndexRequest rpc_request;
        rpc_request.set_collection_name(collection_name);
        rpc_request.set_index_name(index_name);
        return rpc_request;
    };
    return apiHandler<proto::milvus::DropIndexRequest, proto::common::Status>(validate, pre,
                                                                              &MilvusConnection::DropIndex);
}

Status MilvusClientImpl::Insert(const std::string& collection_name, const std::vector<FieldDataPtr>& fields,
                                DmlResults& results) {
    bool enable_dynamic_field;
    auto validate = [this, &collection_name, &fields, &enable_dynamic_field]() {
        CollectionDesc collection_desc;
        auto status = DescribeCollection(collection_name, collection_desc);
        if (!status.IsOk()) {
            return status;
        }

        enable_dynamic_field = collection_desc.Schema().EnableDynamicField();
        const auto& collection_fields = collection_desc.Schema().Fields();

        for (const auto& field : fields) {
            auto it = std::find_if(collection_fields.begin(), collection_fields.end(),
                                   [&field](const FieldSchema& schema) { return schema.Name() == field->Name(); });
            if (it != collection_fields.end()) {
                continue;
            }

            if (!enable_dynamic_field || field->Name() != DynamicFieldName()) {
                return Status{StatusCode::INVALID_AGUMENT, std::string(field->Name() + " is not a valid anns field")};
            }
        }
        return Status::OK();
    };

    auto pre = [&collection_name, &fields, &enable_dynamic_field] {
        proto::milvus::InsertRequest rpc_request;

        rpc_request.set_collection_name(collection_name);
        rpc_request.set_num_rows((*fields.front()).Count());
        for (const auto& field : fields) {
            proto::schema::FieldData data = CreateProtoFieldData(*field);
            if (enable_dynamic_field && field->Name() == DynamicFieldName()) {
                data.set_is_dynamic(true);
            }
            rpc_request.add_fields_data()->CopyFrom(data);
        }
        // std::cout << rpc_request.DebugString() << std::endl;
        return rpc_request;
    };

    auto post = [&results](const proto::milvus::MutationResult& response) {
        auto id_array = CreateIDArray(response.ids());
        results.SetIdArray(std::move(id_array));
        results.SetTimestamp(response.timestamp());
    };

    return apiHandler<proto::milvus::InsertRequest, proto::milvus::MutationResult>(validate, pre,
                                                                                   &MilvusConnection::Insert, post);
}

Status MilvusClientImpl::Delete(const std::string& collection_name, const std::string& expression,
                                DmlResults& results) {
    auto validate = [&collection_name] {
        return collection_name.empty() ? Status{StatusCode::INVALID_AGUMENT, "collection_name cannot be empty!"}
                                       : Status::OK();
    };

    auto pre = [&collection_name, &expression]() {
        proto::milvus::DeleteRequest rpc_request;
        rpc_request.set_collection_name(collection_name);
        rpc_request.set_expr(expression);
        return rpc_request;
    };

    auto post = [&results](const proto::milvus::MutationResult& response) {
        auto id_array = CreateIDArray(response.ids());
        results.SetIdArray(std::move(id_array));
        results.SetTimestamp(response.timestamp());
    };

    return apiHandler<proto::milvus::DeleteRequest, proto::milvus::MutationResult>(validate, pre,
                                                                                   &MilvusConnection::Delete, post);
}

Status MilvusClientImpl::Upsert(const std::string& collection_name, const std::vector<FieldDataPtr>& fields,
                                DmlResults& results) {
    bool enable_dynamic_field;
    auto validate = [this, &collection_name, &fields, &enable_dynamic_field]() {
        CollectionDesc collection_desc;
        auto status = DescribeCollection(collection_name, collection_desc);
        if (!status.IsOk()) {
            return status;
        }

        enable_dynamic_field = collection_desc.Schema().EnableDynamicField();
        const auto& collection_fields = collection_desc.Schema().Fields();

        for (const auto& field : fields) {
            auto it = std::find_if(collection_fields.begin(), collection_fields.end(),
                                   [&field](const FieldSchema& schema) { return schema.Name() == field->Name(); });
            if (it != collection_fields.end()) {
                continue;
            }

            if (!enable_dynamic_field || field->Name() != DynamicFieldName()) {
                return Status{StatusCode::INVALID_AGUMENT, std::string(field->Name() + " is not a valid anns field")};
            }
        }
        return Status::OK();
    };

    auto pre = [&collection_name, &fields, &enable_dynamic_field]() {
        proto::milvus::UpsertRequest rpc_request;
        rpc_request.set_collection_name(collection_name);
        rpc_request.set_num_rows((*fields.front()).Count());
        for (const auto& field : fields) {
            proto::schema::FieldData data = CreateProtoFieldData(*field);
            if (enable_dynamic_field && field->Name() == DynamicFieldName()) {
                data.set_is_dynamic(true);
            }
            rpc_request.add_fields_data()->CopyFrom(data);
        }
        return rpc_request;
    };

    auto post = [&results](const proto::milvus::MutationResult& response) {
        auto id_array = CreateIDArray(response.ids());
        results.SetIdArray(std::move(id_array));
        results.SetTimestamp(response.timestamp());
    };

    return apiHandler<proto::milvus::UpsertRequest, proto::milvus::MutationResult>(validate, pre,
                                                                                   &MilvusConnection::Upsert, post);
}

Status MilvusClientImpl::HybridSearch(SearchResults& results, const std::string& collection_name,
                                      const std::vector<AnnSearchRequest>& reqs, const BaseRanker& ranker, int limit,
                                      const std::vector<std::string>& output_fields,
                                      const std::vector<std::pair<std::string, std::string>>& params, int timeout) {
    auto validate = [this, &collection_name, &reqs, limit]() {
        if (collection_name.empty()) {
            return Status{StatusCode::INVALID_AGUMENT, "Collection name cannot be empty"};
        }

        if (reqs.empty()) {
            return Status{StatusCode::INVALID_AGUMENT, "Search requests cannot be empty"};
        }

        if (limit <= 0) {
            return Status{StatusCode::INVALID_AGUMENT, "Search limit must be positive"};
        }

        CollectionDesc collection_desc;
        auto status = DescribeCollection(collection_name, collection_desc);
        if (!status.IsOk()) {
            return status;
        }

        auto anns_fields = collection_desc.Schema().AnnsFieldNames();
        for (const auto& req : reqs) {
            const auto& field_name = req.AnnsField();
            if (anns_fields.find(field_name) == anns_fields.end()) {
                return Status{StatusCode::INVALID_AGUMENT,
                              std::string(field_name + " is not a valid anns field in collection " + collection_name)};
            }
        }

        return Status::OK();
    };

    auto pre = [&collection_name, &reqs, &ranker, limit, &output_fields, &params]() {
        proto::milvus::HybridSearchRequest hybrid_search_request;
        hybrid_search_request.set_collection_name(collection_name);

        for (const auto& req : reqs) {
            proto::milvus::SearchRequest search_request;
            search_request.set_collection_name(collection_name);
            search_request.set_dsl_type(proto::common::DslType::BoolExprV1);
            if (!req.Expr().empty()) {
                search_request.set_dsl(req.Expr());
            }

            // placeholders
            proto::common::PlaceholderGroup placeholder_group;
            auto& placeholder_value = *placeholder_group.add_placeholders();
            placeholder_value.set_tag("$0");
            auto target = req.TargetVectors();
            if (target->Type() == DataType::BINARY_VECTOR) {
                // bins
                placeholder_value.set_type(proto::common::PlaceholderType::BinaryVector);
                auto& bins_vec = dynamic_cast<BinaryVecFieldData&>(*target);
                for (const auto& bins : bins_vec.Data()) {
                    std::string placeholder_data(reinterpret_cast<const char*>(bins.data()), bins.size());
                    placeholder_value.add_values(std::move(placeholder_data));
                }
                search_request.set_nq(static_cast<int64_t>(bins_vec.Data().size()));
            } else if (target->Type() == DataType::FLOAT_VECTOR) {
                // floats
                placeholder_value.set_type(proto::common::PlaceholderType::FloatVector);
                auto& floats_vec = dynamic_cast<FloatVecFieldData&>(*target);
                for (const auto& floats : floats_vec.Data()) {
                    std::string placeholder_data(reinterpret_cast<const char*>(floats.data()),
                                                 floats.size() * sizeof(float));
                    placeholder_value.add_values(std::move(placeholder_data));
                }
                search_request.set_nq(static_cast<int64_t>(floats_vec.Data().size()));
            } else {
                // SparseFloatVector
                placeholder_value.set_type(proto::common::PlaceholderType::SparseFloatVector);
                auto& sparse_vec = dynamic_cast<SparseFloatVecFieldData&>(*target);
                for (auto sparse : sparse_vec.Data()) {
                    placeholder_value.add_values(SparseFloatVecFieldData::SortAndSerialize(sparse));
                }
                search_request.set_nq(static_cast<int64_t>(sparse_vec.Data().size()));
            }
            search_request.set_placeholder_group(std::move(placeholder_group.SerializeAsString()));

            auto kv_pair = search_request.add_search_params();
            kv_pair->set_key("anns_field");
            kv_pair->set_value(req.AnnsField());

            kv_pair = search_request.add_search_params();
            kv_pair->set_key("topk");
            kv_pair->set_value(std::to_string(req.Limit()));

            for (const auto& param : req.Param()) {
                kv_pair = search_request.add_search_params();
                kv_pair->set_key(param.first);
                kv_pair->set_value(param.second);
            }

            kv_pair = search_request.add_search_params();
            kv_pair->set_key(KeyParams());
            nlohmann::json json = nlohmann::json::object();
            kv_pair->set_value(json.dump());

            hybrid_search_request.add_requests()->CopyFrom(search_request);
        }

        auto ranker_dict = ranker.Dict();

        for (const auto& ranker_dict_item : ranker_dict.items()) {
            auto* kv_pair = hybrid_search_request.add_rank_params();
            kv_pair->set_key(ranker_dict_item.key());

            auto value = ranker_dict_item.value();
            if (value.is_object()) {
                for (auto& item : value.items()) {
                    std::string str = "{\"" + item.key() + "\":" + item.value().get<std::string>() + "}";
                    kv_pair->set_value(str);
                }
            } else if (value.is_array()) {
                kv_pair->set_value(value.dump());
            } else {
                kv_pair->set_value(value.get<std::string>());
            }
        }

        for (const auto& field : output_fields) {
            hybrid_search_request.add_output_fields(field);
        }
        auto* kv_pair = hybrid_search_request.add_rank_params();
        kv_pair->set_key("limit");
        kv_pair->set_value(std::to_string(limit));
        for (const auto& param : params) {
            // round_decimal、offset。。。
            kv_pair = hybrid_search_request.add_rank_params();
            kv_pair->set_key(param.first);
            kv_pair->set_value(param.second);
        }

        return hybrid_search_request;
    };

    auto post = [&results](const proto::milvus::SearchResults& response) {
        auto& result_data = response.results();
        const auto& ids = result_data.ids();
        const auto& scores = result_data.scores();
        const auto& fields_data = result_data.fields_data();
        auto num_of_queries = result_data.num_queries();
        std::vector<int> topks{};
        topks.reserve(result_data.topks_size());
        for (int i = 0; i < result_data.topks_size(); ++i) {
            topks.emplace_back(result_data.topks(i));
        }
        std::vector<SingleResult> single_results;
        single_results.reserve(num_of_queries);
        int offset{0};
        for (int i = 0; i < num_of_queries; ++i) {
            std::vector<float> item_scores;
            std::vector<FieldDataPtr> item_field_data;
            auto item_topk = topks[i];
            item_scores.reserve(item_topk);
            for (int j = 0; j < item_topk; ++j) {
                item_scores.emplace_back(scores.Get(offset + j));
            }
            item_field_data.reserve(fields_data.size());
            for (const auto& field_data : fields_data) {
                item_field_data.emplace_back(std::move(CreateMilvusFieldData(field_data, offset, item_topk)));
            }
            single_results.emplace_back(std::move(CreateIDArray(ids, offset, item_topk)), std::move(item_scores),
                                        std::move(item_field_data));
            offset += item_topk;
        }

        results = std::move(SearchResults(std::move(single_results)));
    };

    return apiHandler<proto::milvus::HybridSearchRequest, proto::milvus::SearchResults>(
        validate, pre, &MilvusConnection::HybridSearch, nullptr, post, GrpcOpts{timeout});
}

Status MilvusClientImpl::Search(const SearchArguments& arguments, SearchResults& results, int timeout) {
    std::string anns_field;
    auto validate = [this, &arguments, &anns_field]() {
        CollectionDesc collection_desc;
        auto status = DescribeCollection(arguments.CollectionName(), collection_desc);
        if (status.IsOk()) {
            // check anns fields
            auto& field_name = arguments.TargetVectors()->Name();
            auto anns_fileds = collection_desc.Schema().AnnsFieldNames();
            if (anns_fileds.find(field_name) != anns_fileds.end()) {
                anns_field = field_name;
            } else {
                return Status{StatusCode::INVALID_AGUMENT, std::string(field_name + " is not a valid anns field")};
            }
            // basic check for extra params
            status = arguments.Validate();
        }
        return status;
    };

    auto pre = [&arguments, &anns_field]() {
        proto::milvus::SearchRequest rpc_request;
        rpc_request.set_collection_name(arguments.CollectionName());
        rpc_request.set_dsl_type(proto::common::DslType::BoolExprV1);
        if (!arguments.Expression().empty()) {
            rpc_request.set_dsl(arguments.Expression());
        }
        for (const auto& output_field : arguments.OutputFields()) {
            rpc_request.add_output_fields(output_field);
        }

        // placeholders
        proto::common::PlaceholderGroup placeholder_group;
        auto& placeholder_value = *placeholder_group.add_placeholders();
        placeholder_value.set_tag("$0");
        auto target = arguments.TargetVectors();
        if (target->Type() == DataType::BINARY_VECTOR) {
            // bins
            placeholder_value.set_type(proto::common::PlaceholderType::BinaryVector);
            auto& bins_vec = dynamic_cast<BinaryVecFieldData&>(*target);
            for (const auto& bins : bins_vec.Data()) {
                std::string placeholder_data(reinterpret_cast<const char*>(bins.data()), bins.size());
                placeholder_value.add_values(std::move(placeholder_data));
            }
            rpc_request.set_nq(static_cast<int64_t>(bins_vec.Data().size()));
        } else {
            // floats
            placeholder_value.set_type(proto::common::PlaceholderType::FloatVector);
            auto& floats_vec = dynamic_cast<FloatVecFieldData&>(*target);
            for (const auto& floats : floats_vec.Data()) {
                std::string placeholder_data(reinterpret_cast<const char*>(floats.data()),
                                             floats.size() * sizeof(float));
                placeholder_value.add_values(std::move(placeholder_data));
            }
            rpc_request.set_nq(static_cast<int64_t>(floats_vec.Data().size()));
        }
        rpc_request.set_placeholder_group(std::move(placeholder_group.SerializeAsString()));

        auto kv_pair = rpc_request.add_search_params();
        kv_pair->set_key("anns_field");
        kv_pair->set_value(anns_field);

        kv_pair = rpc_request.add_search_params();
        kv_pair->set_key("topk");
        kv_pair->set_value(std::to_string(arguments.TopK()));

        kv_pair = rpc_request.add_search_params();
        kv_pair->set_key(KeyMetricType());
        kv_pair->set_value(std::to_string(arguments.MetricType()));

        kv_pair = rpc_request.add_search_params();
        kv_pair->set_key("round_decimal");
        kv_pair->set_value(std::to_string(arguments.RoundDecimal()));

        kv_pair = rpc_request.add_search_params();
        kv_pair->set_key(KeyParams());
        // merge extra params with range search
        auto json = nlohmann::json::parse(arguments.ExtraParams());
        if (arguments.RangeSearch()) {
            json["range_filter"] = arguments.RangeFilter();
            json["radius"] = arguments.Radius();
        }
        kv_pair->set_value(json.dump());

        rpc_request.set_travel_timestamp(arguments.TravelTimestamp());
        rpc_request.set_guarantee_timestamp(arguments.GuaranteeTimestamp());
        return rpc_request;
    };

    auto post = [&results](const proto::milvus::SearchResults& response) {
        auto& result_data = response.results();
        const auto& ids = result_data.ids();
        const auto& scores = result_data.scores();
        const auto& fields_data = result_data.fields_data();
        auto num_of_queries = result_data.num_queries();
        std::vector<int> topks{};
        topks.reserve(result_data.topks_size());
        for (int i = 0; i < result_data.topks_size(); ++i) {
            topks.emplace_back(result_data.topks(i));
        }
        std::vector<SingleResult> single_results;
        single_results.reserve(num_of_queries);
        int offset{0};
        for (int i = 0; i < num_of_queries; ++i) {
            std::vector<float> item_scores;
            std::vector<FieldDataPtr> item_field_data;
            auto item_topk = topks[i];
            item_scores.reserve(item_topk);
            for (int j = 0; j < item_topk; ++j) {
                item_scores.emplace_back(scores.Get(offset + j));
            }
            item_field_data.reserve(fields_data.size());
            for (const auto& field_data : fields_data) {
                item_field_data.emplace_back(std::move(CreateMilvusFieldData(field_data, offset, item_topk)));
            }
            single_results.emplace_back(std::move(CreateIDArray(ids, offset, item_topk)), std::move(item_scores),
                                        std::move(item_field_data));
            offset += item_topk;
        }

        results = std::move(SearchResults(std::move(single_results)));
    };

    return apiHandler<proto::milvus::SearchRequest, proto::milvus::SearchResults>(
        validate, pre, &MilvusConnection::Search, nullptr, post, GrpcOpts{timeout});
}

Status MilvusClientImpl::Query(const QueryArguments& arguments, QueryResults& results, int timeout) {
    auto pre = [&arguments]() {
        proto::milvus::QueryRequest rpc_request;
        rpc_request.set_collection_name(arguments.CollectionName());

        rpc_request.set_expr(arguments.Expression());
        for (const auto& field : arguments.OutputFields()) {
            rpc_request.add_output_fields(field);
        }

        rpc_request.set_travel_timestamp(arguments.TravelTimestamp());
        rpc_request.set_guarantee_timestamp(arguments.GuaranteeTimestamp());

        if (arguments.Limit() > 0) {
            proto::common::KeyValuePair* pair = rpc_request.add_query_params();
            pair->set_key("limit");
            pair->set_value(std::to_string(arguments.Limit()));
        }
        if (arguments.Offset() > 0) {
            proto::common::KeyValuePair* pair = rpc_request.add_query_params();
            pair->set_key("offset");
            pair->set_value(std::to_string(arguments.Offset()));
        }

        return rpc_request;
    };

    auto post = [&results](const proto::milvus::QueryResults& response) {
        std::vector<FieldDataPtr> return_fields{};
        return_fields.reserve(response.fields_data_size());
        for (const auto& field_data : response.fields_data()) {
            return_fields.emplace_back(std::move(CreateMilvusFieldData(field_data)));
        }

        results = std::move(QueryResults(std::move(return_fields)));
    };
    return apiHandler<proto::milvus::QueryRequest, proto::milvus::QueryResults>(pre, &MilvusConnection::Query, post,
                                                                                GrpcOpts{timeout});
}

Status MilvusClientImpl::ShowCollections(std::vector<std::string>& collection_names) {
    auto pre = []() {
        proto::milvus::ShowCollectionsRequest rpc_request;
        rpc_request.set_type(proto::milvus::ShowType::All);
        return rpc_request;
    };

    auto post = [&collection_names](const proto::milvus::ShowCollectionsResponse& response) {
        for (const auto& item : response.collection_names()) {
            collection_names.emplace_back(item);
        }
    };
    return apiHandler<proto::milvus::ShowCollectionsRequest, proto::milvus::ShowCollectionsResponse>(
        pre, &MilvusConnection::ShowCollections, post);
}

Status MilvusClientImpl::DescribeIndex(const std::string& collection_name, const std::string& field_name,
                                       IndexDesc& index_desc) {
    auto validate = [&collection_name, &field_name] {
        return (collection_name.empty() || field_name.empty())
                   ? Status{StatusCode::INVALID_AGUMENT, "collection_name or field_name cannot be empty!"}
                   : Status::OK();
    };

    auto pre = [&collection_name, &field_name]() {
        proto::milvus::DescribeIndexRequest rpc_request;
        rpc_request.set_collection_name(collection_name);
        rpc_request.set_field_name(field_name);
        return rpc_request;
    };

    auto post = [&index_desc, &field_name](const proto::milvus::DescribeIndexResponse& response) {
        auto count = response.index_descriptions_size();
        int poz = -1;
        if (count == 1) {
            poz = 0;
        } else {
            for (int i = 0; i < count; ++i) {
                const auto& rpc_desc = response.index_descriptions(i);
                if (field_name == rpc_desc.field_name()) {
                    poz = i;
                    break;
                }
            }
        }

        if (poz >= 0) {
            const auto& rpc_desc = response.index_descriptions(poz);
            index_desc.SetFieldName(rpc_desc.field_name());
            index_desc.SetIndexName(rpc_desc.index_name());
            index_desc.SetIndexId(rpc_desc.indexid());
            index_desc.SetStateCode(IndexStateCast(rpc_desc.state()));
            index_desc.SetFailReason(rpc_desc.index_state_fail_reason());
            index_desc.SetIndexedRows(rpc_desc.indexed_rows());
            index_desc.SetTotalRows(rpc_desc.total_rows());
            index_desc.SetPendingRows(rpc_desc.pending_index_rows());
            auto index_params_size = rpc_desc.params_size();
            for (int j = 0; j < index_params_size; ++j) {
                const auto& key = rpc_desc.params(j).key();
                const auto& value = rpc_desc.params(j).value();
                if (key == KeyIndexType()) {
                    index_desc.SetIndexType(IndexTypeCast(value));
                } else if (key == KeyMetricType()) {
                    index_desc.SetMetricType(MetricTypeCast(value));
                } else if (key == KeyParams()) {
                    index_desc.ExtraParamsFromJson(value);
                }
            }
        }
    };

    return apiHandler<proto::milvus::DescribeIndexRequest, proto::milvus::DescribeIndexResponse>(
        validate, pre, &MilvusConnection::DescribeIndex, post);
}

Status MilvusClientImpl::GetCollectionStatistics(const std::string& collection_name, CollectionStat& collection_stat) {
    auto validate = [&collection_name] {
        return collection_name.empty() ? Status{StatusCode::INVALID_AGUMENT, "collection_name cannot be empty!"}
                                       : Status::OK();
    };

    auto pre = [&collection_name]() {
        proto::milvus::GetCollectionStatisticsRequest rpc_request;
        rpc_request.set_collection_name(collection_name);
        return rpc_request;
    };

    auto post = [&collection_stat, &collection_name](const proto::milvus::GetCollectionStatisticsResponse& response) {
        collection_stat.SetName(collection_name);
        for (const auto& stat_pair : response.stats()) {
            collection_stat.Emplace(stat_pair.key(), stat_pair.value());
        }
    };

    return apiHandler<proto::milvus::GetCollectionStatisticsRequest, proto::milvus::GetCollectionStatisticsResponse>(
        validate, pre, &MilvusConnection::GetCollectionStatistics, post);
}

Status MilvusClientImpl::GetLoadState(const std::string& collection_name, bool& is_loaded) {
    auto validate = [&collection_name] {
        return collection_name.empty() ? Status{StatusCode::INVALID_AGUMENT, "collection_name cannot be empty!"}
                                       : Status::OK();
    };

    auto pre = [&collection_name]() {
        proto::milvus::GetLoadStateRequest rpc_request;
        rpc_request.set_collection_name(collection_name);
        return rpc_request;
    };

    auto post = [&is_loaded](const proto::milvus::GetLoadStateResponse& response) {
        is_loaded = response.state() == proto::common::LoadStateLoaded;
    };

    return apiHandler<proto::milvus::GetLoadStateRequest, proto::milvus::GetLoadStateResponse>(
        validate, pre, &MilvusConnection::GetLoadState, post);
}
}  // namespace VectorDB
