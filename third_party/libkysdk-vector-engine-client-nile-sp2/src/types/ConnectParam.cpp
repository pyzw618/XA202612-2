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

#include "types/ConnectParam.h"

#include <unistd.h>

#include <string>

namespace VectorDB {
ConnectParam::ConnectParam(std::string appId)
    : app_id_(std::move(appId)), uri_("unix:/tmp/kylin-ai-vector-engine-" + std::to_string(geteuid()) + ".sock") {}

ConnectParam::ConnectParam(std::string appId, const std::string& host, uint16_t port)
    : app_id_(std::move(appId)), uri_(host + ":" + std::to_string(port)) {}

std::string ConnectParam::Uri() const { return uri_; }

uint32_t ConnectParam::ConnectTimeout() const { return connect_timeout_; }

void ConnectParam::SetConnectTimeout(uint32_t timeout) { connect_timeout_ = timeout; }

std::string ConnectParam::AppId() const { return app_id_; }

}  // namespace VectorDB
