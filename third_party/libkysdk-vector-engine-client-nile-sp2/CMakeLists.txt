# Licensed to the LF AI & Data foundation under one
# or more contributor license agreements. See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership. The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

cmake_minimum_required(VERSION 3.5)
project(kysdk-vector-engine-client LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 17)

find_package(PkgConfig REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(SQLiteCpp REQUIRED)
pkg_check_modules(GRPC REQUIRED IMPORTED_TARGET grpc)
pkg_check_modules(SQLCIPHER REQUIRED IMPORTED_TARGET sqlcipher)

file(GLOB_RECURSE SOURCE_LIST ${PROJECT_SOURCE_DIR}/src/*.cpp)

include_directories(${PROJECT_SOURCE_DIR}/include/kysdk-vector-engine-client
        ${PROJECT_SOURCE_DIR}/src/impl
        ${SQLiteCpp_INCLUDE_DIRS}
        ${SQLCIPHER_INCLUDE_DIRS})

find_package(Protobuf REQUIRED)
find_package(KylinAiProto REQUIRED)

kylin_ai_generate_grpc_proto_source(RETURNED_GRPC_SOURCE_FILES vector-db schema common msg feder rg milvus)
message("grpc source files: ${RETURNED_GRPC_SOURCE_FILES}")
kylin_ai_generate_grpc_proto_service(RETURNED_GRPC_SERVICE_FILES vector-db milvus)
message("grpc source files: ${RETURNED_GRPC_SERVICE_FILES}")

add_library(kysdk-vector-engine-client SHARED
        ${SOURCE_LIST}
        ${RETURNED_GRPC_SOURCE_FILES}
        ${RETURNED_GRPC_SERVICE_FILES})

target_link_libraries(kysdk-vector-engine-client
        PUBLIC grpc++
        PUBLIC protobuf
        PUBLIC nlohmann_json::nlohmann_json
        SQLiteCpp
        PkgConfig::SQLCIPHER)

# 设置动态库版本号
set_target_properties(kysdk-vector-engine-client PROPERTIES VERSION 0.0.1 SOVERSION 1)

add_library(kysdk-vector-engine-client-capi SHARED
        capi/c_api_bridge.cpp)
target_link_libraries(kysdk-vector-engine-client-capi
        PUBLIC kysdk-vector-engine-client)
set_target_properties(kysdk-vector-engine-client-capi PROPERTIES VERSION 0.0.1 SOVERSION 1)

# The MemoryHub DEB keeps both libraries together in
# /usr/lib/memoryhub/native.  A relative RUNPATH lets the C API bridge resolve
# the bundled C++ SDK without relying on a global ldconfig entry.
set_target_properties(kysdk-vector-engine-client kysdk-vector-engine-client-capi PROPERTIES
        BUILD_RPATH_USE_ORIGIN ON
        INSTALL_RPATH "$ORIGIN")

install(TARGETS kysdk-vector-engine-client kysdk-vector-engine-client-capi
        DESTINATION ${CMAKE_INSTALL_LIBDIR})

install(FILES capi/c_api_bridge.h
        DESTINATION include)

install(DIRECTORY include/kysdk-vector-engine-client
        DESTINATION include)

install(DIRECTORY usr/ DESTINATION /usr)

if (DEFINED ENABLE_DEMO)
    unset(ENABLE_DEMO CACHE)
endif()
option(ENABLE_DEMO "Build Demo" OFF)
if (ENABLE_DEMO)
    add_subdirectory(demo)
endif(ENABLE_DEMO)
