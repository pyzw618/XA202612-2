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

#include <grpc/grpc.h>
#include <grpcpp/channel.h>
#include <grpcpp/client_context.h>
#include <grpcpp/create_channel.h>
#include <grpcpp/security/credentials.h>
#include <unistd.h>

#include <chrono>
#include <memory>
#include <string>

#include "common.pb.h"
#include "milvus.grpc.pb.h"
#include "milvus.pb.h"
#include "schema.pb.h"
#include "types/ConnectParam.h"
#include "types/Status.h"
#include "types/Utils.h"

namespace VectorDB {
using namespace milvus;

const int RETRY_TIME = 3;

class MilvusConnection {
public:
    /**
     * options for grpc call
     */
    struct GrpcContextOptions {
        /** timeout in milliseconds */
        int timeout{0};

        // constructors
        GrpcContextOptions() = default;
        explicit GrpcContextOptions(int timeout_) : timeout{timeout_} {}
    };

    explicit MilvusConnection(ConnectParam param) : param_(std::move(param)) {}

    virtual ~MilvusConnection();

    Status Connect();

    Status Disconnect();

    Status LoadDBFile(const proto::milvus::LoadDBFileRequest& request, proto::common::Status& response,
                      const GrpcContextOptions& options);

    Status CreateCollection(const proto::milvus::CreateCollectionRequest& request, proto::common::Status& response,
                            const GrpcContextOptions& options);

    Status DropCollection(const proto::milvus::DropCollectionRequest& request, proto::common::Status& response,
                          const GrpcContextOptions& options);

    Status HasCollection(const proto::milvus::HasCollectionRequest& request, proto::milvus::BoolResponse& response,
                         const GrpcContextOptions& options);

    Status LoadCollection(const proto::milvus::LoadCollectionRequest& request, proto::common::Status& response,
                          const GrpcContextOptions& options);

    Status ReleaseCollection(const proto::milvus::ReleaseCollectionRequest& request, proto::common::Status& response,
                             const GrpcContextOptions& options);

    Status DescribeCollection(const proto::milvus::DescribeCollectionRequest& request,
                              proto::milvus::DescribeCollectionResponse& response, const GrpcContextOptions& options);

    Status ShowCollections(const proto::milvus::ShowCollectionsRequest& request,
                           proto::milvus::ShowCollectionsResponse& response, const GrpcContextOptions& options);

    Status CreateIndex(const proto::milvus::CreateIndexRequest& request, proto::common::Status& response,
                       const GrpcContextOptions& options);

    Status DescribeIndex(const proto::milvus::DescribeIndexRequest& request,
                         proto::milvus::DescribeIndexResponse& response, const GrpcContextOptions& options);

    Status DropIndex(const proto::milvus::DropIndexRequest& request, proto::common::Status& response,
                     const GrpcContextOptions& options);

    Status Insert(const proto::milvus::InsertRequest& request, proto::milvus::MutationResult& response,
                  const GrpcContextOptions& options);

    Status Delete(const proto::milvus::DeleteRequest& request, proto::milvus::MutationResult& response,
                  const GrpcContextOptions& options);

    Status Upsert(const proto::milvus::UpsertRequest& request, proto::milvus::MutationResult& response,
                  const GrpcContextOptions& options);

    Status HybridSearch(const proto::milvus::HybridSearchRequest& request, proto::milvus::SearchResults& response,
                        const GrpcContextOptions& options);

    Status Search(const proto::milvus::SearchRequest& request, proto::milvus::SearchResults& response,
                  const GrpcContextOptions& options);

    Status Query(const proto::milvus::QueryRequest& request, proto::milvus::QueryResults& response,
                 const GrpcContextOptions& options);

    Status GetCollectionStatistics(const proto::milvus::GetCollectionStatisticsRequest& request,
                                   proto::milvus::GetCollectionStatisticsResponse& response,
                                   const GrpcContextOptions& options);

    Status GetLoadState(const proto::milvus::GetLoadStateRequest& request,
                        proto::milvus::GetLoadStateResponse& response, const GrpcContextOptions& options);

private:
    std::unique_ptr<proto::milvus::MilvusService::Stub> stub_;
    std::shared_ptr<grpc::Channel> channel_;
    ConnectParam param_;

    static Status StatusByProtoResponse(const proto::common::Status& status) {
        // keys from kylin-ai-vector-engine/src/status.h
        static const std::map<int, StatusCode> recover_code_to_status = {{0, StatusCode::OK},
                                                                         {899, StatusCode::DATABASE_INIT_FAILED}};

        if (recover_code_to_status.find(status.code()) != recover_code_to_status.end()) {
            return Status(recover_code_to_status.at(status.code()), status.reason());
        }

        return Status(StatusCode::SERVER_FAILED, status.reason());
    }

    template <typename Response>
    static Status StatusByProtoResponse(const Response& response) {
        const auto& status = response.status();
        return StatusByProtoResponse(status);
    }

    static StatusCode StatusCodeFromGrpcStatus(const ::grpc::Status& grpc_status) {
        if (grpc_status.error_code() == ::grpc::StatusCode::DEADLINE_EXCEEDED) {
            return StatusCode::TIMEOUT;
        }
        return StatusCode::SERVER_FAILED;
    }

    template <typename Request, typename Response>
    Status grpcCall(const char* name,
                    grpc::Status (proto::milvus::MilvusService::Stub::*func)(grpc::ClientContext*, const Request&,
                                                                             Response*),
                    const Request& request, Response& response, const GrpcContextOptions& options) {
        if (stub_ == nullptr) {
            return {StatusCode::NOT_CONNECTED, "Connection is not ready!"};
        }

        ::grpc::ClientContext context;
        if (options.timeout > 0) {
            auto deadline = std::chrono::system_clock::now() + std::chrono::milliseconds{options.timeout};
            context.set_deadline(deadline);
        }
        context.AddMetadata("app_id", param_.AppId());

        int retryTime = 0;
        ::grpc::Status grpc_status = (stub_.get()->*func)(&context, request, &response);
        while (grpc_status.error_code() == ::grpc::StatusCode::UNAVAILABLE && retryTime <= RETRY_TIME) {
            if (retryTime == RETRY_TIME) {
                std::cerr << "ERROR grpc retry failed, code: " << grpc_status.error_code()
                          << ", msg: " << grpc_status.error_message() << std::endl;
                return {StatusCodeFromGrpcStatus(grpc_status), grpc_status.error_message()};
            }
            std::cout << "WARN grpc failed, code: " << grpc_status.error_code()
                      << ", msg: " << grpc_status.error_message() << ", retry: " << retryTime << std::endl;
            // 断开当前连接
            Disconnect();

            sleep(1);
            retryTime++;
            // 重连
            Status status = Connect();
            if (!status.IsOk()) {
                std::cout << "WARN reconnect milvus failed, code: " << static_cast<int>(status.Code())
                          << ", msg: " << status.Message() << std::endl;
                continue;
            }
            grpc_status = (stub_.get()->*func)(&context, request, &response);
        }

        if (!grpc_status.ok()) {
            return {StatusCodeFromGrpcStatus(grpc_status), grpc_status.error_message()};
        }

        return StatusByProtoResponse(response);
    }
};

}  // namespace VectorDB
