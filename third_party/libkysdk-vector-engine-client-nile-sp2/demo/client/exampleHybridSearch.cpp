#include <iostream>

#include "Database.h"
#include "types/Utils.h"

std::shared_ptr<VectorDB::Database> client = VectorDB::Database::Create();
const std::string collection_name = "HybridSearch";
const std::string field_id_name = "f_id";
const std::string field_context_name = "f_context";
const std::string field_vector_name = "f_vector";
const uint32_t dimension = 4;
const std::string field_sparse_vector_name = "f_sparse_vector";

void CheckStatus(std::string&& prefix, const VectorDB::Status& status) {
    if (!status.IsOk()) {
        std::cout << prefix << " " << static_cast<int>(status.Code()) << ", msg: " << status.Message() << std::endl;
        exit(1);
    }
}

void Connect() {
    VectorDB::ConnectParam connect_param("hello");
    auto status = client->Connect(connect_param);
    CheckStatus("Failed to connect milvus server:", status);
    std::cout << "Connect to milvus server success." << std::endl;
}

void LoadDBFile() {
    auto status = client->LoadDBFile("/home/kylin/.local/share/test1111.db", true, "123456");
    CheckStatus("Failed to load db file:", status);
    std::cout << "Load db to milvus server success." << std::endl;
}

void DropCollection() {
    bool exist;
    auto status = client->HasCollection(collection_name, exist);
    CheckStatus("Failed to HasCollection " + collection_name, status);
    std::cout << collection_name << " collection exist or not: " << exist << std::endl;
    if (!exist) {
        return;
    }

    status = client->DropCollection(collection_name);
    std::cout << "Drop TEST collection code: " << static_cast<int>(status.Code()) << ", msg: " << status.Message()
              << std::endl;
}

void GetLoadState() {
    bool is_loaded;
    auto status = client->GetLoadState(collection_name, is_loaded);
    std::cout << collection_name << " load code: " << static_cast<int>(status.Code()) << ", msg: " << status.Message()
              << ", is_loaded: " << is_loaded << std::endl;
}

void ReleaseCollection() {
    auto status = client->ReleaseCollection(collection_name);
    CheckStatus("Failed to ReleaseCollection " + collection_name, status);
    std::cout << collection_name << " release collection success." << std::endl;
}

void CreateCollection() {
    // 未设置动态字段，不使用自增id
    VectorDB::CollectionSchema collection_schema(collection_name);
    collection_schema.AddField({field_id_name, VectorDB::DataType::INT64, "user id", true, false});
    collection_schema.AddField(
        VectorDB::FieldSchema(field_context_name, VectorDB::DataType::VARCHAR, "user context").WithMaxLength(1024));
    collection_schema.AddField(VectorDB::FieldSchema(field_vector_name, VectorDB::DataType::FLOAT_VECTOR, "user vector")
                                   .WithDimension(dimension));
    collection_schema.AddField(
        VectorDB::FieldSchema(field_sparse_vector_name, VectorDB::DataType::SPARSE_FLOAT_VECTOR, "user sparse vector"));

    auto status = client->CreateCollection(collection_schema);
    CheckStatus("Failed to create collection:", status);
    std::cout << "Successfully create collection." << std::endl;
}

void CreateIndex() {
    // 给向量列建个索引
    VectorDB::IndexDesc vector_index_desc(field_vector_name, "vector_index", VectorDB::IndexType::FLAT,
                                          VectorDB::MetricType::COSINE);

    auto status = client->CreateIndex(collection_name, vector_index_desc);
    CheckStatus("Failed to create vector index:", status);

    // 给稀疏向量列建个索引
    VectorDB::IndexDesc sparse_vector_index_desc(field_sparse_vector_name, "sparse_vector_index",
                                                 VectorDB::IndexType::SPARSE_INVERTED_INDEX, VectorDB::MetricType::IP);

    status = client->CreateIndex(collection_name, sparse_vector_index_desc);
    CheckStatus("Failed to create sparse vector index:", status);

    std::cout << "Successfully create index." << std::endl;
}

void ShowCollections() {
    std::vector<std::string> collections;
    auto status = client->ShowCollections(collections);
    CheckStatus("Failed to ShowCollections", status);
    std::cout << "ShowCollections: [";
    for (int i = 0; i < collections.size(); i++) {
        if (i > 0) {
            std::cout << ", ";
        }
        std::cout << collections[i];
    }
    std::cout << "]" << std::endl;
}

void DescribeIndex() {
    VectorDB::IndexDesc index_desc;
    auto status = client->DescribeIndex(collection_name, field_vector_name, index_desc);
    CheckStatus("Failed to DescribeIndex " + collection_name, status);
    std::cout << collection_name << " DescribeIndex: field name: " << index_desc.FieldName()
              << ", id: " << index_desc.IndexId() << ", index name: " << index_desc.IndexName()
              << ", metric type: " << std::to_string(index_desc.MetricType())
              << ", index type: " << std::to_string(index_desc.IndexType())
              << ", state: " << static_cast<int>(index_desc.StateCode()) << ", fail reason: " << index_desc.FailReason()
              << ", params: " << index_desc.ExtraParams() << std::endl;
}

void Insert() {
    std::vector<int64_t> insert_id = {1, 2};
    std::vector<std::string> insert_context = {"hello", "world"};
    std::vector<std::vector<float>> insert_vectors = {{0.1, 0.2, 0.3, 0.4}, {0.4, 0.5, 0.6, 0.7}};
    std::vector<std::vector<std::pair<uint32_t, float>>> sparse_vectors = {{{123, 0.1}, {456, 0.2}},
                                                                           {{12, 0.8}, {45, 0.9}}};

    std::vector<VectorDB::FieldDataPtr> fields_data{
        std::make_shared<VectorDB::Int64FieldData>(field_id_name, insert_id),
        std::make_shared<VectorDB::VarCharFieldData>(field_context_name, insert_context),
        std::make_shared<VectorDB::FloatVecFieldData>(field_vector_name, insert_vectors),
        std::make_shared<VectorDB::SparseFloatVecFieldData>(field_sparse_vector_name, sparse_vectors)};
    VectorDB::DmlResults results;
    auto status = client->Insert(collection_name, fields_data, results);
    CheckStatus("Failed to insert:", status);
    std::cout << "Successfully insert " << results.IdArray().IntIDArray().size() << " rows." << std::endl;
}

void Search() {
    // 设置返回条数
    VectorDB::SearchArguments arguments(collection_name, 10);
    // 查询输出哪些列
    arguments.AddOutputField(field_id_name);
    arguments.AddOutputField(field_context_name);
    arguments.AddOutputField(field_vector_name);
    arguments.AddOutputField(field_sparse_vector_name);
    // 可加查询条件，写法参考：https://milvus.io/docs/zh/boolean.md
    // arguments.SetExpression(field_id_name + " in [0,1,2,3]");

    // 设置要搜索的向量，示例查询 id=0 的数据
    std::cout << "Searching the Id.0 entity..." << std::endl;
    std::vector<float> q_vector = {0.1, 0.2, 0.3, 0.4};
    arguments.AddTargetVector(field_vector_name, move(q_vector));

    VectorDB::SearchResults results;
    auto status = client->Search(arguments, results);
    CheckStatus("Failed to search:", status);
    std::cout << "Search success. result size: " << results.Results().size() << std::endl;

    for (const auto& result : results.Results()) {
        auto ids = result.Ids().IntIDArray();
        auto distances = result.Scores();
        if (ids.size() != distances.size()) {
            std::cout << "Illegal result! ids:" << ids.size() << ", distances:" << distances.size() << std::endl;
            continue;
        }

        if (ids.empty()) {
            std::cout << "Empty result!" << std::endl;
            continue;
        }

        auto id_field = result.OutputField(field_id_name);
        std::shared_ptr<VectorDB::Int64FieldData> id_field_ptr =
            std::static_pointer_cast<VectorDB::Int64FieldData>(id_field);
        auto id_data = id_field_ptr->Data();
        std::cout << "Search id rows: " << id_data.size() << std::endl;

        auto context_field = result.OutputField(field_context_name);
        std::shared_ptr<VectorDB::VarCharFieldData> context_field_ptr =
            std::static_pointer_cast<VectorDB::VarCharFieldData>(context_field);
        auto context_data = context_field_ptr->Data();
        std::cout << "Search context rows: " << context_data.size() << std::endl;

        auto vector_field = result.OutputField(field_vector_name);
        std::shared_ptr<VectorDB::FloatVecFieldData> vector_field_ptr =
            std::static_pointer_cast<VectorDB::FloatVecFieldData>(vector_field);
        auto vector_data = vector_field_ptr->Data();
        std::cout << "Search vector rows: " << vector_data.size() << std::endl;

        auto sparse_field = result.OutputField(field_sparse_vector_name);
        std::shared_ptr<VectorDB::SparseFloatVecFieldData> sparse_field_ptr =
            std::static_pointer_cast<VectorDB::SparseFloatVecFieldData>(sparse_field);
        auto sparse_data = sparse_field_ptr->Data();
        std::cout << "Search sparse vector rows: " << sparse_data.size() << std::endl;

        for (size_t i = 0; i < ids.size(); i++) {
            std::cout << "ID: " << ids[i] << "\tDistance: " << distances[i] << "\t" << id_field_ptr->Name() << ": "
                      << id_data[i] << "\t" << context_field_ptr->Name() << ": " << context_data[i] << "\t"
                      << vector_field_ptr->Name() << ": [";
            for (int j = 0; j < vector_data[i].size(); j++) {
                if (j > 0) {
                    std::cout << ", ";
                }
                std::cout << vector_data[i][j];
            }
            std::cout << "]\t" << sparse_field_ptr->Name() << ": [";
            for (int j = 0; j < sparse_data[i].size(); j++) {
                if (j > 0) {
                    std::cout << ", ";
                }
                std::cout << sparse_data[i][j].first << ":" << sparse_data[i][j].second;
            }
            std::cout << "]" << std::endl;
        }
    }
}

void HybridSearch() {
    VectorDB::AnnSearchRequest request1(field_vector_name, 10);
    std::vector<float> q_vector = {0.1, 0.2, 0.3, 0.4};
    request1.AddTargetVector(field_vector_name, std::move(q_vector));

    VectorDB::AnnSearchRequest request2(field_sparse_vector_name, 10);
    std::vector<std::pair<uint32_t, float>> q_sparse_vector = {{126, 0.1}, {456, 0.8}};
    request2.AddTargetVector(field_sparse_vector_name, std::move(q_sparse_vector));

    VectorDB::RRFRanker ranker;

    VectorDB::SearchResults results;
    VectorDB::Status status =
        client->HybridSearch(results, collection_name, {request1, request2}, ranker, 10,
                             {field_id_name, field_context_name, field_vector_name, field_sparse_vector_name});
    CheckStatus("Failed to search:", status);
    std::cout << "HybridSearch success. result size: " << results.Results().size() << std::endl;

    for (const auto& result : results.Results()) {
        auto ids = result.Ids().IntIDArray();
        auto distances = result.Scores();
        if (ids.size() != distances.size()) {
            std::cout << "Illegal result! ids:" << ids.size() << ", distances:" << distances.size() << std::endl;
            continue;
        }

        if (ids.empty()) {
            std::cout << "Empty result!" << std::endl;
            continue;
        }

        auto id_field = result.OutputField(field_id_name);
        std::shared_ptr<VectorDB::Int64FieldData> id_field_ptr =
            std::static_pointer_cast<VectorDB::Int64FieldData>(id_field);
        auto id_data = id_field_ptr->Data();
        std::cout << "Search id rows: " << id_data.size() << std::endl;

        auto context_field = result.OutputField(field_context_name);
        std::shared_ptr<VectorDB::VarCharFieldData> context_field_ptr =
            std::static_pointer_cast<VectorDB::VarCharFieldData>(context_field);
        auto context_data = context_field_ptr->Data();
        std::cout << "Search context rows: " << context_data.size() << std::endl;

        auto vector_field = result.OutputField(field_vector_name);
        std::shared_ptr<VectorDB::FloatVecFieldData> vector_field_ptr =
            std::static_pointer_cast<VectorDB::FloatVecFieldData>(vector_field);
        auto vector_data = vector_field_ptr->Data();
        std::cout << "Search vector rows: " << vector_data.size() << std::endl;

        auto sparse_field = result.OutputField(field_sparse_vector_name);
        std::shared_ptr<VectorDB::SparseFloatVecFieldData> sparse_field_ptr =
            std::static_pointer_cast<VectorDB::SparseFloatVecFieldData>(sparse_field);
        auto sparse_data = sparse_field_ptr->Data();
        std::cout << "Search sparse vector rows: " << sparse_data.size() << std::endl;

        for (size_t i = 0; i < ids.size(); i++) {
            std::cout << "ID: " << ids[i] << "\tDistance: " << distances[i] << "\t" << id_field_ptr->Name() << ": "
                      << id_data[i] << "\t" << context_field_ptr->Name() << ": " << context_data[i] << "\t"
                      << vector_field_ptr->Name() << ": [";
            for (int j = 0; j < vector_data[i].size(); j++) {
                if (j > 0) {
                    std::cout << ", ";
                }
                std::cout << vector_data[i][j];
            }
            std::cout << "]\t" << sparse_field_ptr->Name() << ": [";
            for (int j = 0; j < sparse_data[i].size(); j++) {
                if (j > 0) {
                    std::cout << ", ";
                }
                std::cout << sparse_data[i][j].first << ":" << sparse_data[i][j].second;
            }
            std::cout << "]" << std::endl;
        }
    }
}

void Query() {
    VectorDB::QueryArguments arguments;
    arguments.SetCollectionName(collection_name);
    // 查询输出哪些列
    arguments.AddOutputField(field_id_name);
    arguments.AddOutputField(field_context_name);
    arguments.AddOutputField(field_vector_name);
    arguments.AddOutputField(field_sparse_vector_name);
    // 查询条件，写法参考：https://milvus.io/docs/zh/boolean.md
    arguments.SetExpression(field_id_name + " == 1");

    VectorDB::QueryResults queryResults;
    auto status = client->Query(arguments, queryResults);
    CheckStatus("Failed to query:", status);
    std::cout << "Query success. output field num: " << queryResults.OutputFields().size() << std::endl;

    auto id_field = queryResults.GetFieldByName(field_id_name);
    std::shared_ptr<VectorDB::Int64FieldData> id_field_ptr =
        std::static_pointer_cast<VectorDB::Int64FieldData>(id_field);
    auto id_data = id_field_ptr->Data();
    std::cout << "Query id rows: " << id_data.size() << std::endl;
    if (id_data.empty()) {
        std::cout << "Query Empty result!" << std::endl;
        return;
    }

    auto context_field = queryResults.GetFieldByName(field_context_name);
    std::shared_ptr<VectorDB::VarCharFieldData> context_field_ptr =
        std::static_pointer_cast<VectorDB::VarCharFieldData>(context_field);
    auto context_data = context_field_ptr->Data();
    std::cout << "Query context rows: " << context_data.size() << std::endl;

    auto vectorField = queryResults.GetFieldByName(field_vector_name);
    std::shared_ptr<VectorDB::FloatVecFieldData> vector_field_ptr =
        std::static_pointer_cast<VectorDB::FloatVecFieldData>(vectorField);
    auto vector_data = vector_field_ptr->Data();
    std::cout << "Query vector rows: " << vector_data.size() << std::endl;

    auto sparse_field = queryResults.GetFieldByName(field_sparse_vector_name);
    std::shared_ptr<VectorDB::SparseFloatVecFieldData> sparse_field_ptr =
        std::static_pointer_cast<VectorDB::SparseFloatVecFieldData>(sparse_field);
    auto sparse_data = sparse_field_ptr->Data();
    std::cout << "Query sparse vector rows: " << sparse_data.size() << std::endl;

    for (size_t i = 0; i < id_data.size(); i++) {
        std::cout << id_field_ptr->Name() << ": " << id_data[i] << "\t" << context_field_ptr->Name() << ": "
                  << context_data[i] << "\t" << vector_field_ptr->Name() << ": [";
        for (int j = 0; j < vector_data[i].size(); j++) {
            if (j > 0) {
                std::cout << ", ";
            }
            std::cout << vector_data[i][j];
        }
        std::cout << "]\t" << sparse_field_ptr->Name() << ": [";
        for (int j = 0; j < sparse_data[i].size(); j++) {
            if (j > 0) {
                std::cout << ", ";
            }
            std::cout << sparse_data[i][j].first << ":" << sparse_data[i][j].second;
        }
        std::cout << "]" << std::endl;
    }
}

void Upsert() {
    std::vector<int64_t> upsert_id = {1};
    std::vector<std::string> upsert_context = {"hi"};
    std::vector<std::vector<float>> upsert_vectors = {{0.11, 0.22, 0.33, 0.44}};
    std::vector<std::vector<std::pair<uint32_t, float>>> sparse_vectors = {{{66, 0.6}, {88, 0.8}}};

    std::vector<VectorDB::FieldDataPtr> fields_data{
        std::make_shared<VectorDB::Int64FieldData>(field_id_name, upsert_id),
        std::make_shared<VectorDB::VarCharFieldData>(field_context_name, upsert_context),
        std::make_shared<VectorDB::FloatVecFieldData>(field_vector_name, upsert_vectors),
        std::make_shared<VectorDB::SparseFloatVecFieldData>(field_sparse_vector_name, sparse_vectors)};

    VectorDB::DmlResults results;
    auto status = client->Upsert(collection_name, fields_data, results);
    CheckStatus("Failed to upsert:", status);
    std::cout << "Successfully upsert " << results.IdArray().IntIDArray().size() << " rows." << std::endl;
}

int main() {
    std::cout << "Example HybridSearch start..." << std::endl;

    Connect();
    LoadDBFile();

    DropCollection();
    GetLoadState();

    CreateCollection();
    CreateIndex();
    GetLoadState();
    ShowCollections();
    DescribeIndex();

    ReleaseCollection();
    GetLoadState();

    std::cout << "=========== Insert ===========" << std::endl;
    Insert();
    std::cout << "=========== Search ===========" << std::endl;
    Search();
    std::cout << "=========== HybridSearch ===========" << std::endl;
    HybridSearch();
    std::cout << "=========== Query ===========" << std::endl;
    Query();
    std::cout << "=========== Upsert ===========" << std::endl;
    Upsert();
    std::cout << "=========== Search ===========" << std::endl;
    Search();
    std::cout << "=========== HybridSearch ===========" << std::endl;
    HybridSearch();
    std::cout << "=========== Query ===========" << std::endl;
    Query();

    GetLoadState();

    return 0;
}
