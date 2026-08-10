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

#include "MilvusConnection.h"

#include <memory>

using grpc::Channel;
using grpc::ClientContext;
using grpc::ClientReader;
using grpc::ClientReaderWriter;
using grpc::ClientWriter;
using grpc::Status;
using Stub = milvus::proto::milvus::MilvusService::Stub;

namespace VectorDB {
using namespace milvus;

MilvusConnection::~MilvusConnection() { Disconnect(); }

Status MilvusConnection::Connect() {
    if (param_.AppId().empty()) {
        return {StatusCode::APPID_EMPTY, "Connect param app_id is empty."};
    }

    const auto& uri = param_.Uri();
    std::shared_ptr<::grpc::ChannelCredentials> credentials = ::grpc::InsecureChannelCredentials();
    ::grpc::ChannelArguments args;
    args.SetMaxSendMessageSize(-1);     // max send message size: 2GB
    args.SetMaxReceiveMessageSize(-1);  // max receive message size: 2GB

    channel_ = ::grpc::CreateCustomChannel(uri, credentials, args);
    auto connected = channel_->WaitForConnected(std::chrono::system_clock::now() +
                                                std::chrono::milliseconds{param_.ConnectTimeout()});
    if (connected) {
        stub_ = proto::milvus::MilvusService::NewStub(channel_);
        return Status::OK();
    }

    std::string reason = "Failed to connect uri: " + uri;
    return {StatusCode::NOT_CONNECTED, reason};
}

Status MilvusConnection::Disconnect() {
    stub_.reset();
    channel_.reset();
    return Status::OK();
}

Status MilvusConnection::LoadDBFile(const proto::milvus::LoadDBFileRequest& request, proto::common::Status& response,
                                    const GrpcContextOptions& options) {
    return grpcCall("LoadDBFile", &Stub::LoadDBFile, request, response, options);
}

Status MilvusConnection::CreateCollection(const proto::milvus::CreateCollectionRequest& request,
                                          proto::common::Status& response, const GrpcContextOptions& options) {
    return grpcCall("CreateCollection", &Stub::CreateCollection, request, response, options);
}

Status MilvusConnection::DropCollection(const proto::milvus::DropCollectionRequest& request,
                                        proto::common::Status& response, const GrpcContextOptions& options) {
    return grpcCall("DropCollection", &Stub::DropCollection, request, response, options);
}

Status MilvusConnection::HasCollection(const proto::milvus::HasCollectionRequest& request,
                                       proto::milvus::BoolResponse& response, const GrpcContextOptions& options) {
    return grpcCall("HasCollection", &Stub::HasCollection, request, response, options);
}

Status MilvusConnection::LoadCollection(const proto::milvus::LoadCollectionRequest& request,
                                        proto::common::Status& response, const GrpcContextOptions& options) {
    return grpcCall("LoadCollection", &Stub::LoadCollection, request, response, options);
}

Status MilvusConnection::ReleaseCollection(const proto::milvus::ReleaseCollectionRequest& request,
                                           proto::common::Status& response, const GrpcContextOptions& options) {
    return grpcCall("ReleaseCollection", &Stub::ReleaseCollection, request, response, options);
}

Status MilvusConnection::DescribeCollection(const proto::milvus::DescribeCollectionRequest& request,
                                            proto::milvus::DescribeCollectionResponse& response,
                                            const GrpcContextOptions& options) {
    return grpcCall("DescribeCollection", &Stub::DescribeCollection, request, response, options);
}

Status MilvusConnection::ShowCollections(const proto::milvus::ShowCollectionsRequest& request,
                                         proto::milvus::ShowCollectionsResponse& response,
                                         const GrpcContextOptions& options) {
    return grpcCall("ShowCollections", &Stub::ShowCollections, request, response, options);
}

Status MilvusConnection::CreateIndex(const proto::milvus::CreateIndexRequest& request, proto::common::Status& response,
                                     const GrpcContextOptions& options) {
    return grpcCall("CreateIndex", &Stub::CreateIndex, request, response, options);
}

Status MilvusConnection::DescribeIndex(const proto::milvus::DescribeIndexRequest& request,
                                       proto::milvus::DescribeIndexResponse& response,
                                       const GrpcContextOptions& options) {
    return grpcCall("DescribeIndex", &Stub::DescribeIndex, request, response, options);
}

Status MilvusConnection::DropIndex(const proto::milvus::DropIndexRequest& request, proto::common::Status& response,
                                   const GrpcContextOptions& options) {
    return grpcCall("DropIndex", &Stub::DropIndex, request, response, options);
}

Status MilvusConnection::Insert(const proto::milvus::InsertRequest& request, proto::milvus::MutationResult& response,
                                const GrpcContextOptions& options) {
    return grpcCall("Insert", &Stub::Insert, request, response, options);
}

Status MilvusConnection::Delete(const proto::milvus::DeleteRequest& request, proto::milvus::MutationResult& response,
                                const GrpcContextOptions& options) {
    return grpcCall("Delete", &Stub::Delete, request, response, options);
}

Status MilvusConnection::Upsert(const proto::milvus::UpsertRequest& request, proto::milvus::MutationResult& response,
                                const GrpcContextOptions& options) {
    return grpcCall("Upsert", &Stub::Upsert, request, response, options);
}

Status MilvusConnection::HybridSearch(const proto::milvus::HybridSearchRequest& request,
                                      proto::milvus::SearchResults& response, const GrpcContextOptions& options) {
    return grpcCall("HybridSearch", &Stub::HybridSearch, request, response, options);
}

Status MilvusConnection::Search(const proto::milvus::SearchRequest& request, proto::milvus::SearchResults& response,
                                const GrpcContextOptions& options) {
    return grpcCall("Search", &Stub::Search, request, response, options);
}

Status MilvusConnection::Query(const proto::milvus::QueryRequest& request, proto::milvus::QueryResults& response,
                               const GrpcContextOptions& options) {
    return grpcCall("Query", &Stub::Query, request, response, options);
}

Status MilvusConnection::GetCollectionStatistics(const proto::milvus::GetCollectionStatisticsRequest& request,
                                                 proto::milvus::GetCollectionStatisticsResponse& response,
                                                 const GrpcContextOptions& options) {
    return grpcCall("GetCollectionStatistics", &Stub::GetCollectionStatistics, request, response, options);
}

Status MilvusConnection::GetLoadState(const proto::milvus::GetLoadStateRequest& request,
                                      proto::milvus::GetLoadStateResponse& response,
                                      const GrpcContextOptions& options) {
    return grpcCall("GetLoadState", &Stub::GetLoadState, request, response, options);
}
}  // namespace VectorDB
