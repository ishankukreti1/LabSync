
#include "Database.h"
#include <mysql_connection.h>

Database::Database(
    const std::string& host,
    const std::string& user,
    const std::string& pass,
    const std::string& schema
){
    driver = sql::mysql::get_mysql_driver_instance();

    sql::ConnectOptionsMap options;
    options["hostName"] = std::string("127.0.0.1");
    options["port"] = 3306;
    options["userName"] = user;
    options["password"] = pass;
    options["schema"] = schema;

    con.reset(driver->connect(options));
}

