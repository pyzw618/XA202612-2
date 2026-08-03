#include "DatabaseTools.h"

int main() {
    // PRAGMA key='{}'
    VectorDB::ConvertToEncryptDBFile("/home/kylin/code/libkysdk-vector-engine-client/demo/tools/default.db",
                                     "/home/kylin/code/libkysdk-vector-engine-client/demo/tools/encrypt.db",
                                     "Kylin-ai-runtime_20250805");
    return 0;
}
