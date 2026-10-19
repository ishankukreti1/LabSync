cmake_minimum_required(VERSION 3.16)
project(LabSync LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)

# Default to Release build type so runtime library matches MySQL Connector DLL (-MD)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# Set or auto-detect MySQL Connector/C++ installation directory
set(MYSQLCPPCONN_ROOT "" CACHE PATH "MySQL Connector/C++ installation directory")
if(NOT MYSQLCPPCONN_ROOT)
  if(EXISTS "C:/Program Files/MySQL/MySQL Connector C++ 26.7")
    set(MYSQLCPPCONN_ROOT "C:/Program Files/MySQL/MySQL Connector C++ 26.7")
  elseif(EXISTS "C:/Program Files/MySQL/MySQL Connector C++ 8.0")
    set(MYSQLCPPCONN_ROOT "C:/Program Files/MySQL/MySQL Connector C++ 8.0")
  endif()
endif()

if(NOT MYSQLCPPCONN_ROOT)
  message(FATAL_ERROR "Set MYSQLCPPCONN_ROOT to your MySQL Connector/C++ folder")
endif()

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

include_directories(include "${MYSQLCPPCONN_ROOT}/include" "${MYSQLCPPCONN_ROOT}/include/jdbc")
link_directories("${MYSQLCPPCONN_ROOT}/lib64/vs14" "${MYSQLCPPCONN_ROOT}/lib64")
add_executable(LabSync
    main.cpp
    src/Database.cpp
    src/LabSyncService.cpp
    src/SchedulingEngine.cpp
    src/Scheduler.cpp
    src/DeadlockPrevention.cpp
    include/Database.h
    include/DeadlockPrevention.h
    include/LabSyncService.h
    include/Models.h
    include/Scheduler.h
)
target_link_libraries(LabSync mysqlcppconn)

# Automatically copy necessary MySQL connector runtime DLLs to output directory
add_custom_command(TARGET LabSync POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${MYSQLCPPCONN_ROOT}/lib64/mysqlcppconn-10-vs14.dll"
        $<TARGET_FILE_DIR:LabSync>
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${MYSQLCPPCONN_ROOT}/lib64/libcrypto-3-x64.dll"
        $<TARGET_FILE_DIR:LabSync>
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${MYSQLCPPCONN_ROOT}/lib64/libssl-3-x64.dll"
        $<TARGET_FILE_DIR:LabSync>
    COMMENT "Copying MySQL Connector runtime DLLs to output directory"
)

# Web bridge: same C++ business logic, separate non-interactive entry point.
add_executable(LabSyncBridge
    scheduler_bridge.cpp src/Database.cpp src/LabSyncService.cpp
    src/SchedulingEngine.cpp
    src/Scheduler.cpp src/DeadlockPrevention.cpp)
target_link_libraries(LabSyncBridge mysqlcppconn)
add_custom_command(TARGET LabSyncBridge POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${MYSQLCPPCONN_ROOT}/lib64/mysqlcppconn-10-vs14.dll"
        $<TARGET_FILE_DIR:LabSyncBridge>
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${MYSQLCPPCONN_ROOT}/lib64/libcrypto-3-x64.dll"
        $<TARGET_FILE_DIR:LabSyncBridge>
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${MYSQLCPPCONN_ROOT}/lib64/libssl-3-x64.dll"
        $<TARGET_FILE_DIR:LabSyncBridge>)
