#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>
#include <exception>
#include "Database.h"
#include "LabSyncService.h"

// One-shot, noninteractive entry point for Flask. Stdout is exactly one JSON object.
static std::string jsonEscape(const std::string& s) {
    std::string out;
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { out += '\\'; out += c; }
        else if (c == '\n') out += "\\n";
        else if (c == '\r') out += "\\r";
        else if (c == '\t') out += "\\t";
        else if (c < 0x20) out += '?';
        else out += c;
    }
    return out;
}
static std::string env(const char* name, const char* fallback="") {
    const char* value = std::getenv(name);
    return value ? value : fallback;
}
int main(int argc, char** argv) {
    if (argc != 2 || std::string(argv[1]) != "schedule") {
        std::cout << "{\"success\":false,\"message\":\"Expected: LabSyncBridge schedule\"}\n";
        return 2;
    }
    try {
        const std::string host = env("MYSQL_HOST", "127.0.0.1");
        const std::string port = env("MYSQL_PORT", "3309");
        Database db("tcp://" + host + ":" + port,
                    env("MYSQL_USER", "root"), env("MYSQL_PASSWORD"),
                    env("MYSQL_DB", "labsync"));
        LabSyncService service(db);
        std::ostringstream log;
        auto* old = std::cout.rdbuf(log.rdbuf());
        try { service.runScheduler(); }
        catch (...) { std::cout.rdbuf(old); throw; }
        std::cout.rdbuf(old);
        const std::string output = log.str();
        // Legacy runScheduler catches SQL errors internally; don't claim success.
        const bool finished = output.find("Scheduler completed:") != std::string::npos;
        int allocated = 0, waiting = 0;
        if (finished) {
            auto pos = output.find("Scheduler completed:");
            std::istringstream counts(output.substr(pos + 20));
            counts >> allocated;
            std::string word;
            counts >> word >> waiting;
        }
        std::cout << "{\"success\":" << (finished ? "true" : "false")
                  << ",\"allocated\":" << allocated
                  << ",\"waiting\":" << waiting
                  << ",\"message\":\"" << jsonEscape(finished ? "C++ scheduler finished" : "C++ scheduler did not finish")
                  << "\",\"logs\":[\"" << jsonEscape(output) << "\"]}\n";
        return finished ? 0 : 1;
    } catch (const std::exception& e) {
        std::cout << "{\"success\":false,\"message\":\"" << jsonEscape(e.what()) << "\"}\n";
        return 1;
    }
}
