#pragma once
#include <memory>
#include <string>
#include <mysql_driver.h>
#include <mysql_connection.h>
#include <cppconn/statement.h>
#include <cppconn/prepared_statement.h>
#include <cppconn/resultset.h>
#include <cppconn/exception.h>

class Database {
    sql::mysql::MySQL_Driver* driver{};
    std::unique_ptr<sql::Connection> con;
public:
    Database(const std::string& host,const std::string& user,const std::string& pass,const std::string& schema);
    sql::Connection* get(){ return con.get(); }
    bool ok() const { return con && !con->isClosed(); }
};
