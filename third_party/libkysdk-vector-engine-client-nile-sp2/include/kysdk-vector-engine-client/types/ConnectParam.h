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

#include <cstdint>
#include <string>

namespace VectorDB {

/**
 * @brief Connection parameters. Used by Database::Connect()
 */
class ConnectParam {
public:
    /**
     * @brief Constructor
     */
    explicit ConnectParam(std::string appId);

    /**
     * @brief for test
     */
    ConnectParam(std::string appId, const std::string& host, uint16_t port);

    /**
     * @brief Uri for connecting to the vector engine.
     */
    std::string Uri() const;

    /**
     * @brief Connect timeout in milliseconds.
     */
    uint32_t ConnectTimeout() const;

    /**
     * @brief Set connect timeout in milliseconds.
     */
    void SetConnectTimeout(uint32_t timeout);

    std::string AppId() const;

private:
    std::string uri_;
    uint32_t connect_timeout_ = 5000;
    std::string app_id_;
};

}  // namespace VectorDB
