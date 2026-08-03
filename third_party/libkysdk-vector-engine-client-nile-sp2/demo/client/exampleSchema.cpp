#include <unistd.h>

#include <iostream>
#include <random>

#include "Database.h"
#include "types/Utils.h"

using namespace std;
using namespace VectorDB;

shared_ptr<Database> client = Database::Create();
string collection_name = "TEST";
const string field_id_name = "identity";
const string field_age_name = "age";
const string field_face_name = "face";
const uint32_t dimension = 4;
const int64_t row_count = 10;
vector<int64_t> insert_ids;
vector<std::string> insert_ages;
vector<std::vector<float>> insert_vectors;
default_random_engine ran(time(nullptr));

void CheckStatus(string&& prefix, const Status& status) {
    if (!status.IsOk()) {
        cout << prefix << " code: " << static_cast<int>(status.Code()) << ", msg: " << status.Message() << endl;
        exit(1);
    }
}

void Connect() {
    ConnectParam connect_param("hello2");
    auto status = client->Connect(connect_param);
    CheckStatus("Failed to connect milvus server:", status);
    cout << "Connect to milvus server success." << endl;
}

void LoadDBFile() {
    auto status = client->LoadDBFile("/home/hezhe/.local/share/test2222.db", true, "123456");
    CheckStatus("Failed to load db file:", status);
    cout << "Load db to milvus server success." << endl;
}

void DropCollection() {
    auto status = client->DropCollection(collection_name);
    cout << "Drop TEST collection code: " << static_cast<int>(status.Code()) << ", msg: " << status.Message() << endl;
}

void CreateCollection() {
    // 通过 CollectionSchema 设置数据库列：identity（主键）、age、face（向量）
    CollectionSchema collection_schema(collection_name);
    collection_schema.AddField({field_id_name, DataType::INT64, "user id", true, false});
    collection_schema.AddField(FieldSchema(field_age_name, DataType::VARCHAR, "user age").WithMaxLength(10));
    collection_schema.AddField(
        FieldSchema(field_face_name, DataType::FLOAT_VECTOR, "face signature").WithDimension(dimension));
    collection_schema.AddField({"BOOL", DataType::BOOL, "BOOL"});
    collection_schema.AddField({"FLOAT", DataType::FLOAT, "FLOAT"});
    collection_schema.AddField({"DOUBLE", DataType::DOUBLE, "DOUBLE"});
    collection_schema.AddField(FieldSchema("ARRAY", DataType::ARRAY, "ARRAY").WithElementType(DataType::INT64));
    collection_schema.AddField({"JSON", DataType::JSON, "JSON"});

    // 给向量列建个索引
    IndexDesc index_desc(field_face_name, "face_index", IndexType::FLAT, MetricType::L2);

    auto status = client->CreateCollection(collection_schema, index_desc);
    CheckStatus("Failed to create collection:", status);
    cout << "Successfully create collection." << endl;
}

void Insert() {
    insert_ids.clear();
    insert_ages.clear();
    insert_vectors.clear();
    uniform_int_distribution<int> int_gen(1, 100);
    uniform_real_distribution<float> float_gen(0.0, 1.0);
    uniform_real_distribution<double> double_gen(0.0, 1.0);
    std::vector<bool> insert_bool;
    std::vector<float> insert_float;
    std::vector<double> insert_double;
    std::vector<std::vector<int64_t>> insert_array;
    std::vector<nlohmann::json> insert_json;
    for (auto i = 0; i < row_count; ++i) {
        insert_ids.push_back(i);
        insert_ages.push_back(std::to_string(int_gen(ran)));
        vector<float> vector(dimension);
        for (auto j = 0; j < dimension; ++j) {
            vector[j] = float_gen(ran);
        }
        insert_vectors.emplace_back(vector);

        insert_bool.push_back(i);
        insert_float.push_back(float_gen(ran));
        insert_double.push_back(double_gen(ran));
        insert_array.push_back({i, i + 1});
        insert_json.push_back({std::string(1, static_cast<char>('a' + i)), 100 * i});
    }

    vector<FieldDataPtr> fields_data{make_shared<Int64FieldData>(field_id_name, insert_ids),
                                     make_shared<VarCharFieldData>(field_age_name, insert_ages),
                                     make_shared<FloatVecFieldData>(field_face_name, insert_vectors),
                                     make_shared<BoolFieldData>("BOOL", insert_bool),
                                     make_shared<FloatFieldData>("FLOAT", insert_float),
                                     make_shared<DoubleFieldData>("DOUBLE", insert_double),
                                     make_shared<ArrayFieldData<int64_t, DataType::INT64>>("ARRAY", insert_array),
                                     make_shared<JsonFieldData>("JSON", insert_json)};
    DmlResults dml_results;
    auto status = client->Insert(collection_name, fields_data, dml_results);
    CheckStatus("Failed to insert:", status);
    cout << "Successfully insert " << dml_results.IdArray().IntIDArray().size() << " rows." << endl;
}

void Search() {
    SearchArguments arguments;
    arguments.SetCollectionName(collection_name);
    arguments.SetTopK(10);
    arguments.SetMetricType(MetricType::L2);  // 要与索引一致
    arguments.AddOutputField(field_age_name);
    arguments.AddOutputField("BOOL");
    arguments.AddOutputField("FLOAT");
    arguments.AddOutputField("DOUBLE");
    arguments.AddOutputField("ARRAY");
    arguments.AddOutputField("JSON");
    // arguments.SetExpression("FLOAT > 0.5");

    uniform_int_distribution<int64_t> int64_gen(0, row_count - 1);
    int64_t q_number = int64_gen(ran);
    vector<float> q_vector = insert_vectors[q_number];
    arguments.AddTargetVector(field_face_name, move(q_vector));
    cout << "Searching the No." << q_number << " entity..." << endl;

    SearchResults search_results{};
    auto status = client->Search(arguments, search_results, 5000);
    CheckStatus("Failed to search:", status);
    cout << "Search success." << endl;

    for (auto& result : search_results.Results()) {
        auto& ids = result.Ids().IntIDArray();
        auto& distances = result.Scores();
        if (ids.size() != distances.size()) {
            cout << "Illegal result!" << endl;
            continue;
        }

        if (ids.empty()) {
            std::cout << "Empty result!" << std::endl;
            continue;
        }

        auto age_field = result.OutputField(field_age_name);
        auto age_field_ptr = static_pointer_cast<VarCharFieldData>(age_field);
        auto age_data = age_field_ptr->Data();

        auto bool_field = result.OutputField("BOOL");
        auto bool_field_ptr = static_pointer_cast<BoolFieldData>(bool_field);
        auto bool_data = bool_field_ptr->Data();

        auto float_field = result.OutputField("FLOAT");
        auto float_field_ptr = static_pointer_cast<FloatFieldData>(float_field);
        auto float_data = float_field_ptr->Data();

        auto double_field = result.OutputField("DOUBLE");
        auto double_field_ptr = static_pointer_cast<DoubleFieldData>(double_field);
        auto double_data = double_field_ptr->Data();

        auto array_field = result.OutputField("ARRAY");
        auto array_field_ptr = static_pointer_cast<ArrayFieldData<int64_t, DataType::INT64>>(array_field);
        auto array_data = array_field_ptr->Data();

        auto json_field = result.OutputField("JSON");
        auto json_field_ptr = static_pointer_cast<JsonFieldData>(json_field);
        auto json_data = json_field_ptr->Data();

        for (size_t i = 0; i < ids.size(); ++i) {
            cout << "ID: " << ids[i] << "\tDistance: " << distances[i] << "\tAge: " << age_data[i]
                 << "\tBOOL: " << bool_data[i] << "\tFLOAT: " << float_data[i] << "\tDOUBLE: " << double_data[i]
                 << "\tARRAY: [";
            for (int j = 0; j < array_data[i].size(); j++) {
                if (j > 0) {
                    std::cout << ", ";
                }
                std::cout << array_data[i][j];
            }
            cout << "]\tJSON: " << json_data[i] << endl;
        }
    }
}

void ShowCollections() {
    std::vector<std::string> result;
    auto status = client->ShowCollections(result);
    CheckStatus("Failed to show collections:", status);
    for (int i = 0; i < result.size(); ++i) {
        if (i == 0) {
            std::cout << result[i];
        } else {
            std::cout << ", " << result[i];
        }
    }
    std::cout << std::endl;
}

void DescribeIndex() {
    VectorDB::IndexDesc index_desc;
    auto status = client->DescribeIndex(collection_name, field_face_name, index_desc);
    CheckStatus("Failed to DescribeIndex: ", status);
    std::cout << collection_name << " DescribeIndex: field name: " << index_desc.FieldName()
              << ", id: " << index_desc.IndexId() << ", index name: " << index_desc.IndexName()
              << ", metric type: " << std::to_string(index_desc.MetricType())
              << ", index type: " << std::to_string(index_desc.IndexType())
              << ", state: " << static_cast<int>(index_desc.StateCode()) << ", fail reason: " << index_desc.FailReason()
              << ", params: " << index_desc.ExtraParams() << std::endl;
}

int main() {
    cout << "Example start..." << endl;

    Connect();
    LoadDBFile();

    DropCollection();
    ShowCollections();
    CreateCollection();
    ShowCollections();
    DescribeIndex();

    Insert();
    Search();
    // DropCollection();
    //
    // collection_name = "TEST1";
    // DropCollection();
    // CreateCollection();
    // Insert();
    // Search();
    // DropCollection();

    return 0;
}
