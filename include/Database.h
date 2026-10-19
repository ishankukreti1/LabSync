#pragma once

#include <memory>
#include <string>

#if __has_include(<jdbc/mysql_connection.h>)
    #include <jdbc/mysql_connection.h>
    #include <jdbc/cppconn/statement.h>
    #include <jdbc/cppconn/prepared_statement.h>
    #include <jdbc/cppconn/resultset.h>
    #include <jdbc/cppconn/exception.h>
#elif __has_include(<mysql_connection.h>)
    #include <mysql_connection.h>
    #include <cppconn/statement.h>
    #include <cppconn/prepared_statement.h>
    #include <cppconn/resultset.h>
    #include <cppconn/exception.h>
#else
    namespace sql {
        class Connection;
        class Statement;
        class PreparedStatement;
        class ResultSet;
        class SQLException;
    }
#endif

class Database {
    std::unique_ptr<sql::Connection> con;
    void initSchema(const std::string& schema);

public:
    Database(const std::string& host, const std::string& user, const std::string& pass, const std::string& schema);
    ~Database();

    // Prevent copying: Database owns a unique DB connection resource
    Database(const Database&) = delete;
    Database& operator=(const Database&) = delete;

    // Move operations
    Database(Database&&) noexcept;
    Database& operator=(Database&&) noexcept;

    sql::Connection* get() const;
    bool ok() const;
};
