cmake_minimum_required(VERSION 3.16)
project(LabSync LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)

# Set this when configuring, e.g.
# cmake -S . -B build -DMYSQLCPPCONN_ROOT="C:/Program Files/MySQL/MySQL Connector C++ 8.0"
set(MYSQLCPPCONN_ROOT "" CACHE PATH "MySQL Connector/C++ installation directory")
if(NOT MYSQLCPPCONN_ROOT)
  message(FATAL_ERROR "Set MYSQLCPPCONN_ROOT to your MySQL Connector/C++ folder")
endif()
include_directories(include "${MYSQLCPPCONN_ROOT}/include" "${MYSQLCPPCONN_ROOT}/include/jdbc")
link_directories("${MYSQLCPPCONN_ROOT}/lib64/vs14" "${MYSQLCPPCONN_ROOT}/lib64")
add_executable(LabSync main.cpp src/Database.cpp src/LabSyncService.cpp src/Scheduler.cpp src/DeadlockPrevention.cpp)
target_link_libraries(LabSync mysqlcppconn)
