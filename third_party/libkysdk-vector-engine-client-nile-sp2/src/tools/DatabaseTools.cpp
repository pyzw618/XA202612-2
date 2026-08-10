#include "DatabaseTools.h"

#include <iostream>

#include "SQLiteCpp/Database.h"

namespace VectorDB {

bool ConvertToEncryptDBFile(const std::string& db_file, const std::string& encrypt_file, const std::string& key) {
    SQLite::Database db(db_file, SQLite::OPEN_READWRITE | SQLite::OPEN_CREATE);

    int ret = db.exec("ATTACH DATABASE '" + std::string(encrypt_file) + "' AS encrypted KEY '" + key + "'");
    if (ret != 0) {
        std::cerr << "ATTACH DATABASE failed." << std::endl;
        return false;
    }

    ret = db.exec("SELECT sqlcipher_export('encrypted')");
    if (ret != 0) {
        std::cerr << "Exec sqlcipher_export failed." << std::endl;
        return false;
    }

    ret = db.exec("DETACH DATABASE encrypted");
    if (ret != 0) {
        std::cerr << "DETACH DATABASE failed." << std::endl;
        return false;
    }
    std::cout << "convert to encrypt db success." << std::endl;
    return true;
}

}  // namespace VectorDB
