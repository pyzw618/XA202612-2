#pragma once

#include <iostream>
#include <random>

#include "Database.h"

class Example {
public:
    // 里面调用了 connect
    Example();

    void LoadDBFile();

    bool HasCollection();

    void CreateCollection();

    void DropCollection();

    void Insert();
    // 根据向量查询
    void Search();
    // 根据条件查询，比如主键
    int64_t Query();
    // 根据主键更新
    void Upsert(int64_t id);

    void Delete();

    ~Example();

private:
    std::shared_ptr<VectorDB::Database> client;
    std::string collection_name = "TEST";
    int dimension = 4;
};
