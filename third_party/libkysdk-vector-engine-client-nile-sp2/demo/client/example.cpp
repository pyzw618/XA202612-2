#include "example.h"

using namespace std;
using namespace VectorDB;

vector<vector<float>> insert_vectors;
vector<nlohmann::json> insert_jsons;

void CheckStatus(string&& prefix, const Status& status) {
    if (!status.IsOk()) {
        cout << prefix << " " << static_cast<int>(status.Code()) << " " << status.Message() << endl;
        exit(1);
    }
}

Example::Example() {
    client = Database::Create();
    /**
     * connect 有两种调用方式：
     * 1、传入ConnectParam配置安全信息等，参考 exampleSchema.cpp
     * 2、简化方式：无需传参，未设置安全信息
     */
    auto status = client->Connect(ConnectParam("test"));
    CheckStatus("Failed to connect milvus server:", status);
    cout << "Connect to milvus server success." << endl;
}

void Example::LoadDBFile() {
    auto status = client->LoadDBFile("/home/kylin/.local/share/test.db", true, "123456");
    CheckStatus("Failed to load db file:", status);
    cout << "Load db to milvus server success." << endl;
}

bool Example::HasCollection() {
    bool exist;
    auto status = client->HasCollection(collection_name, exist);
    CheckStatus("Failed to HasCollection " + collection_name, status);
    cout << collection_name << " collection exist or not: " << exist << endl;
    return exist;
}

void Example::CreateCollection() {
    if (HasCollection()) {
        return;
    }

    /**
     * create collection 有两种调用方式：
     * 1、传入schema和index，参考 exampleSchema.cpp
     * 2、简化方式：只传name和dim，默认只创建 id 和 vector field，id默认开启自增，默认开启动态字段
     */
    auto status = client->CreateCollection(collection_name, dimension);
    CheckStatus("Failed to create collection:", status);
    cout << "Successfully create collection." << endl;
}

void Example::DropCollection() {
    auto status = client->DropCollection(collection_name);
    CheckStatus("Failed to drop TEST collection:", status);
    cout << "Drop TEST collection success." << endl;
}

/**
    {"id": 1, "vector": rng.random((1, dim))[0], "a": 100, "g": 101},
    {"id": 2, "vector": rng.random((1, dim))[0], "b": 200, "h": 201},
    {"id": 3, "vector": rng.random((1, dim))[0], "c": 300, "i": 301},
    {"id": 4, "vector": rng.random((1, dim))[0], "d": 400, "j": 401},
    {"id": 5, "vector": rng.random((1, dim))[0], "e": 500, "k": 501},
    {"id": 6, "vector": rng.random((1, dim))[0], "f": 600, "l": 601},
 */
void GenerateData(int dimension) {
    uniform_int_distribution<int> int_gen(1, 100);
    uniform_real_distribution<float> float_gen(0.0, 1.0);
    default_random_engine ran(time(nullptr));
    int row_count = 6;
    string seed = "abcdefghijklmn";

    for (auto i = 0; i < row_count; ++i) {
        // insert_ids.push_back(i + 1);

        vector<float> vector(dimension);
        for (auto j = 0; j < dimension; ++j) {
            vector[j] = float_gen(ran);
        }
        insert_vectors.emplace_back(vector);

        nlohmann::json value = nlohmann::json::object();
        string key;
        key += seed[i];
        value[key] = 100 * (i + 1);
        key = "";
        key += seed[i + 6];
        value[key] = 100 * (i + 1) + 1;
        insert_jsons.push_back(value);
    }
}

void Example::Insert() {
    GenerateData(dimension);

    // 设置动态扩展字段，列名必须使用 DYNAMIC_FIELD_NAME
    // 快捷创建collection的方式，要用默认字段的名称
    // 如果开启了id自增，无需传入 make_shared<Int64FieldData>(DEFAULT_ID_FIELD_NAME, insert_ids)
    vector<FieldDataPtr> fields_data{make_shared<FloatVecFieldData>(DEFAULT_VECTOR_FIELD_NAME, insert_vectors),
                                     make_shared<JsonFieldData>(DYNAMIC_FIELD_NAME, insert_jsons)};
    DmlResults dml_results;
    auto status = client->Insert(collection_name, fields_data, dml_results);
    CheckStatus("Failed to insert:", status);
    cout << "Successfully insert " << dml_results.IdArray().IntIDArray().size() << " rows." << endl;
}

void Example::Search() {
    // 设置返回条数
    SearchArguments arguments(collection_name, 10);
    // 查询输出哪些列
    arguments.AddOutputField(DEFAULT_ID_FIELD_NAME);
    arguments.AddOutputField(DYNAMIC_FIELD_NAME);
    arguments.AddOutputField(DEFAULT_VECTOR_FIELD_NAME);
    // 可加查询条件，写法参考：https://milvus.io/docs/zh/boolean.md
    // arguments.SetExpression(field_id_name + " in [0,1,2,3]");
    // set to strong guarantee so that the search is executed after the inserted data is persisted
    arguments.SetGuaranteeTimestamp(GuaranteeStrongTs());

    // 设置要搜索的向量，示例查询 id=2 的数据
    cout << "Searching the Id.2 entity..." << endl;
    vector<float> q_vector = insert_vectors[1];
    arguments.AddTargetVector(DEFAULT_VECTOR_FIELD_NAME, move(q_vector));

    SearchResults search_results{};
    auto status = client->Search(arguments, search_results);
    CheckStatus("Failed to search:", status);
    cout << "Search success. result size: " << search_results.Results().size() << endl;

    for (auto& result : search_results.Results()) {
        auto& ids = result.Ids().IntIDArray();
        auto& distances = result.Scores();
        if (ids.size() != distances.size()) {
            cout << "Illegal result!" << endl;
            continue;
        }

        if (ids.empty()) {
            cout << "Empty result!" << endl;
            continue;
        }

        auto idField = result.OutputField(DEFAULT_ID_FIELD_NAME);
        shared_ptr<Int64FieldData> idFieldPtr = static_pointer_cast<Int64FieldData>(idField);
        auto& idData = idFieldPtr->Data();
        cout << "Search id rows: " << idData.size() << endl;

        auto jsonField = result.OutputField(DYNAMIC_FIELD_NAME);
        shared_ptr<JsonFieldData> jsonFieldPtr = static_pointer_cast<JsonFieldData>(jsonField);
        auto& jsonData = jsonFieldPtr->Data();
        cout << "Search json rows: " << jsonData.size() << endl;

        auto vectorField = result.OutputField(DEFAULT_VECTOR_FIELD_NAME);
        shared_ptr<FloatVecFieldData> vectorFieldPtr = static_pointer_cast<FloatVecFieldData>(vectorField);
        auto& vectorData = vectorFieldPtr->Data();
        cout << "Search vector rows: " << vectorData.size() << endl;

        for (size_t i = 0; i < ids.size(); ++i) {
            cout << "ID: " << ids[i] << "\tDistance: " << distances[i] << "\t" << idFieldPtr->Name() << ": "
                 << idData[i] << "\t" << jsonFieldPtr->Name() << ": " << jsonData[i] << "\tvector: [";
            for (const auto& item : vectorData[i]) {
                cout << item << ", ";
            }
            cout << "]" << endl;

            // validate the age value
            // if (insert_ids[ids[i]] != idData[i]) {
            //     cout << "ERROR! The returned value doesn't match the inserted value" << endl;
            // }
        }
    }
}

int64_t Example::Query() {
    QueryArguments arguments;
    arguments.SetCollectionName(collection_name);
    // 查询输出哪些列
    arguments.AddOutputField(DEFAULT_ID_FIELD_NAME);
    arguments.AddOutputField(DYNAMIC_FIELD_NAME);
    arguments.AddOutputField(DEFAULT_VECTOR_FIELD_NAME);
    // 查询条件，写法参考：https://milvus.io/docs/zh/boolean.md
    arguments.SetExpression("b == 200");

    QueryResults queryResults;
    auto status = client->Query(arguments, queryResults);
    CheckStatus("Failed to query:", status);
    cout << "Query success. output field num: " << queryResults.OutputFields().size() << endl;

    FieldDataPtr idField = queryResults.GetFieldByName(DEFAULT_ID_FIELD_NAME);
    shared_ptr<Int64FieldData> idFieldPtr = static_pointer_cast<Int64FieldData>(idField);
    auto& idData = idFieldPtr->Data();
    cout << "Query id rows: " << idData.size() << endl;

    FieldDataPtr jsonField = queryResults.GetFieldByName(DYNAMIC_FIELD_NAME);
    shared_ptr<JsonFieldData> jsonFieldPtr = static_pointer_cast<JsonFieldData>(jsonField);
    auto& jsonData = jsonFieldPtr->Data();
    cout << "Query json rows: " << jsonData.size() << endl;

    FieldDataPtr vectorField = queryResults.GetFieldByName(DEFAULT_VECTOR_FIELD_NAME);
    shared_ptr<FloatVecFieldData> vectorFieldPtr = static_pointer_cast<FloatVecFieldData>(vectorField);
    auto& vectorData = vectorFieldPtr->Data();
    cout << "Query vector rows: " << vectorData.size() << endl;

    if (idData.empty()) {
        return 0;
    }

    for (int i = 0; i < idData.size(); ++i) {
        cout << idFieldPtr->Name() << ": " << idData[i] << "\t" << jsonFieldPtr->Name() << ": " << jsonData[i].dump()
             << "\t" << vectorFieldPtr->Name() << ": [";
        for (const auto& item : vectorData[i]) {
            cout << item << ", ";
        }
        cout << "]" << endl;
    }

    return idData[0];
}

// 更新数据是根据主键 id，示例是用Query() 返回的id值
void Example::Upsert(int64_t id) {
    nlohmann::json value = nlohmann::json::object();
    value["b"] = 200;
    value["z"] = 205;

    vector<FieldDataPtr> fields_data{
        make_shared<Int64FieldData>(DEFAULT_ID_FIELD_NAME, vector<int64_t>{id}),
        make_shared<FloatVecFieldData>(DEFAULT_VECTOR_FIELD_NAME, vector<vector<float>>{insert_vectors[0]}),
        make_shared<JsonFieldData>(DYNAMIC_FIELD_NAME, vector<nlohmann::json>{value})};

    DmlResults results;
    auto status = client->Upsert(collection_name, fields_data, results);
    CheckStatus("Failed to upsert:", status);
    cout << "Successfully upsert " << results.IdArray().IntIDArray().size() << " rows." << endl;
}

void Example::Delete() {
    // string expression = "b == 200 || b == 300";
    // string expression = "b not in [ 1,2 ]";
    string expression = "b < 200";
    DmlResults results;
    auto status = client->Delete(collection_name, expression, results);
    CheckStatus("Failed to delete:", status);
    cout << "Successfully Delete " << results.IdArray().IntIDArray().size() << " rows." << endl;
}

Example::~Example() {
    auto status = client->Disconnect();
    CheckStatus("Failed to Disconnect milvus server:", status);
    cout << "Disconnect to milvus server success." << endl;
}

int main() {
    cout << "Example start..." << endl;

    shared_ptr<Example> example = make_shared<Example>();

    example->LoadDBFile();

    // drop the collection if it exists
    example->DropCollection();

    example->CreateCollection();

    example->Insert();

    cout << "=========== 查询数据 ===========" << endl;
    example->Search();
    int64_t id = example->Query();

    cout << "=========== 修改数据后查询数据 ===========" << endl;
    example->Upsert(id);
    example->Search();
    example->Query();

    cout << "=========== 删除数据后查询数据 ===========" << endl;
    example->Delete();
    example->Search();
    example->Query();

    example->DropCollection();

    return 0;
}
