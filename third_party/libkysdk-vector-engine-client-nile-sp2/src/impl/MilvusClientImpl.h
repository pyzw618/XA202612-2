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

#include <memory>

#include "Database.h"
#include "MilvusConnection.h"

/**
 *  @brief namespace milvus
 */
namespace VectorDB {

class MilvusClientImpl : public Database {
public:
    MilvusClientImpl() = default;
    virtual ~MilvusClientImpl();

    Status Connect(const ConnectParam& connect_param) final;

    Status Disconnect() final;

    Status LoadDBFile(const std::string& db_file, bool encrypt, const std::string& key) final;

    Status CreateCollection(const CollectionSchema& schema) final;

    Status CreateCollection(const std::string& collection_name, int dim, bool auto_id, bool enable_dynamic_field) final;

    Status CreateCollection(const CollectionSchema& schema, const IndexDesc& index_desc) final;

    Status HasCollection(const std::string& collection_name, bool& has) final;

    Status DropCollection(const std::string& collection_name) final;

    Status LoadCollection(const std::string& collection_name) final;

    Status ReleaseCollection(const std::string& collection_name) final;

    Status CreateIndex(const std::string& collection_name, const IndexDesc& index_desc) final;

    Status Insert(const std::string& collection_name, const std::vector<FieldDataPtr>& fields,
                  DmlResults& results) final;

    Status Delete(const std::string& collection_name, const std::string& expression, DmlResults& results) final;

    Status Upsert(const std::string& collection_name, const std::vector<FieldDataPtr>& fields,
                  DmlResults& results) final;

    Status HybridSearch(SearchResults& results, const std::string& collection_name,
                        const std::vector<AnnSearchRequest>& reqs, const BaseRanker& ranker, int limit,
                        const std::vector<std::string>& output_fields,
                        const std::vector<std::pair<std::string, std::string>>& params, int timeout) final;

    Status Search(const SearchArguments& arguments, SearchResults& results, int timeout) final;

    Status Query(const QueryArguments& arguments, QueryResults& results, int timeout) final;

    Status DescribeCollection(const std::string& collection_name, CollectionDesc& collection_desc) final;

    Status ShowCollections(std::vector<std::string>& collection_names) final;

    Status DescribeIndex(const std::string& collection_name, const std::string& field_name,
                         IndexDesc& index_desc) final;

    Status DropIndex(const std::string& collection_name, const std::string& index_name) final;

    Status GetCollectionStatistics(const std::string& collection_name, CollectionStat& collection_stat) final;

    Status GetLoadState(const std::string& collection_name, bool& is_loaded) final;

public:
    using GrpcOpts = MilvusConnection::GrpcContextOptions;

    /**
     * Internal wait for status query done.
     *
     * @param [in] query_function one time query for return Status, return TIMEOUT status if not done
     * @param [in] progress_monitor timeout setting for waiting progress
     * @return Status, the final status
     */
    // static Status WaitForStatus(const std::function<Status(Progress&)>& query_function,
    //                             const ProgressMonitor& progress_monitor);

    /**
     * @brief template for public api call
     *        validate -> pre -> rpc -> wait_for_status -> post
     */
    template <typename Request, typename Response>
    Status apiHandler(const std::function<Status(void)>& validate, std::function<Request(void)> pre,
                      Status (MilvusConnection::*rpc)(const Request&, Response&, const GrpcOpts&),
                      std::function<Status(const Response&)> wait_for_status, std::function<void(const Response&)> post,
                      const GrpcOpts& options = GrpcOpts{}) {
        if (connection_ == nullptr) {
            return {StatusCode::NOT_CONNECTED, "Connection is not ready!"};
        }

        if (validate) {
            auto status = validate();
            if (!status.IsOk()) {
                return status;
            }
        }

        Request rpc_request = pre();
        Response rpc_response;
        auto status = std::bind(rpc, connection_.get(), std::placeholders::_1, std::placeholders::_2,
                                std::placeholders::_3)(rpc_request, rpc_response, options);
        if (!status.IsOk()) {
            // response's status already checked in connection class
            return status;
        }

        if (wait_for_status) {
            status = wait_for_status(rpc_response);
        }

        if (status.IsOk() && post) {
            post(rpc_response);
        }
        return status;
    }

    /**
     * @brief template for public api call
     */
    template <typename Request, typename Response>
    Status apiHandler(std::function<Status(void)> validate, std::function<Request(void)> pre,
                      Status (MilvusConnection::*rpc)(const Request&, Response&, const GrpcOpts&),
                      std::function<void(const Response&)> post, const GrpcOpts& options = GrpcOpts{}) {
        return apiHandler(validate, pre, rpc, std::function<Status(const Response&)>{}, post, options);
    }

    /**
     * @brief template for public api call
     */
    template <typename Request, typename Response>
    Status apiHandler(std::function<Status(void)> validate, std::function<Request(void)> pre,
                      Status (MilvusConnection::*rpc)(const Request&, Response&, const GrpcOpts&),
                      const GrpcOpts& options = GrpcOpts{}) {
        return apiHandler(validate, pre, rpc, std::function<Status(const Response&)>{},
                          std::function<void(const Response&)>{}, options);
    }

    /**
     * @brief template for public api call
     */
    template <typename Request, typename Response>
    Status apiHandler(std::function<Request(void)> pre,
                      Status (MilvusConnection::*rpc)(const Request&, Response&, const GrpcOpts&),
                      std::function<void(const Response&)> post, const GrpcOpts& options = GrpcOpts{}) {
        return apiHandler(std::function<Status(void)>{}, pre, rpc, std::function<Status(const Response&)>{}, post,
                          options);
    }

    /**
     * @brief template for public api call
     */
    template <typename Request, typename Response>
    Status apiHandler(std::function<Request(void)> pre,
                      Status (MilvusConnection::*rpc)(const Request&, Response&, const GrpcOpts&),
                      const GrpcOpts& options = GrpcOpts{}) {
        return apiHandler(std::function<Status(void)>{}, pre, rpc, std::function<Status(const Response&)>{},
                          std::function<void(const Response&)>{}, options);
    }

private:
    std::shared_ptr<MilvusConnection> connection_;
};

}  // namespace VectorDB
