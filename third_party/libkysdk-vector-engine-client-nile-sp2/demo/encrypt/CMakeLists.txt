cmake_minimum_required(VERSION 3.5)

project(demo-encrypt LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 17)

add_executable(tool-encrypt main.cpp)
target_link_libraries(tool-encrypt PUBLIC kysdk-vector-engine-client)
