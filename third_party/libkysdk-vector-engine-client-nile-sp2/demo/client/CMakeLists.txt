cmake_minimum_required(VERSION 3.5)

project(demo LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 17)

add_executable(client-schema exampleSchema.cpp)
target_link_libraries(client-schema PUBLIC kysdk-vector-engine-client)

add_executable(client-example example.cpp example.h)
target_link_libraries(client-example PUBLIC kysdk-vector-engine-client)

add_executable(client-hybrid exampleHybridSearch.cpp)
target_link_libraries(client-hybrid PUBLIC kysdk-vector-engine-client)

add_executable(client-dynamic-hybrid exampleDynamicHybridSearch.cpp)
target_link_libraries(client-dynamic-hybrid PUBLIC kysdk-vector-engine-client)
