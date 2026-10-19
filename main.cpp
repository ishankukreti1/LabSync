#include <iostream>
#include <string>
#include <fstream>
#include <limits>
#include <memory>
#include <algorithm>
#include "Database.h"
#include "LabSyncService.h"
#include "DeadlockPrevention.h"

using namespace std;

static string trim(const string& str) {
    size_t first = str.find_first_not_of(" \t\r\n");
    if (first == string::npos) return "";
    size_t last = str.find_last_not_of(" \t\r\n");
    return str.substr(first, (last - first + 1));
}

int main() {
    cout << "========================================\n";
    cout << "          LabSync Exam System           \n";
    cout << "========================================\n";

    unique_ptr<Database> db;

    // 1. Attempt automatic connection using saved db_config.json or default password
    string autoPassword = "";
    int autoPort = 3309;~
    ifstream cf("db_config.json");
    if (cf.is_open()) {
        string line;
        while (getline(cf, line)) {
            auto pos = line.find("\"MYSQL_PASSWORD\":");
            if (pos != string::npos) {
                auto firstQuote = line.find('"', pos + 17);
                if (firstQuote != string::npos) {
                    auto secondQuote = line.find('"', firstQuote + 1);
                    if (secondQuote != string::npos) {
                        auto parsed = line.substr(firstQuote + 1, secondQuote - firstQuote - 1);
                        if (!parsed.empty()) {
                            autoPassword = parsed;
                        }
                    }
                }
            }
            auto portPos = line.find("\"MYSQL_PORT\":");
            if (portPos != string::npos) {
                try {
                    auto numStr = line.substr(portPos + 13);
                    auto digits = numStr.substr(numStr.find_first_of("0123456789"));
                    autoPort = stoi(digits);
                } catch (...) {}
            }
        }
    }

    string connUrl = "tcp://127.0.0.1:" + to_string(autoPort);

    try {
        cout << "[Attempting automatic connection to MySQL on port " << autoPort << "...]" << endl;
        db = make_unique<Database>(
            connUrl,
            "root",
            autoPassword,
            "labsync"
        );
        cout << "[Database connected and initialized successfully!]\n";
    } catch (...) {
        // Automatic connection failed; prompt user below
    }

    while (!db) {
        cout << "\nEnter MySQL root password (press Enter if blank, or 'q' to quit): ";
        string rawPassword;
        if (!getline(cin, rawPassword)) {
            cout << "\nInput closed. Exiting.\n";
            return 0;
        }

        string trimmed = trim(rawPassword);
        if (trimmed == "q" || trimmed == "Q" || trimmed == "exit") {
            cout << "\nExiting LabSync.\n";
            return 0;
        }

        try {
            cout << "[Connecting to MySQL...]" << endl;
            db = make_unique<Database>(
                connUrl,
                "root",
                trimmed,
                "labsync"
            );
            cout << "[Database connected and initialized successfully!]\n";
        } catch (sql::SQLException& e) {
            cout << "\nMySQL Connection Failed (Code " << e.getErrorCode() << "): " << e.what() << "\n";
            cout << "Please verify that the MySQL service is running and the password is correct.\n";
        } catch (const exception& e) {
            cout << "\nConnection error: " << e.what() << "\n";
        }
    }

    try {
        LabSyncService app(*db);

        int role = -1;
        while (role != 0) {
            cout << "\n===== LABSYNC MAIN MENU =====\n";
            cout << "1 Student\n";
            cout << "2 Admin\n";
            cout << "0 Exit\n";
            cout << "Choice: ";

            if (!(cin >> role)) {
                if (cin.eof()) {
                    cout << "\nInput closed. Exiting.\n";
                    break;
                }
                cin.clear();
                cin.ignore(numeric_limits<streamsize>::max(), '\n');
                cout << "Invalid input! Please choose 1, 2, or 0.\n";
                continue;
            }

            if (role == 1) {
                int c = -1;
                while (c != 0) {
                    cout << "\n--- STUDENT MENU ---\n";
                    cout << "1 Register\n";
                    cout << "2 View exams\n";
                    cout << "3 View slots\n";
                    cout << "4 Book slot\n";
                    cout << "5 View my bookings\n";
                    cout << "6 Cancel booking\n";
                    cout << "0 Back\n";
                    cout << "Choice: ";

                    c = -1;
                    if (!(cin >> c)) {
                        if (cin.eof()) {
                            cout << "\nInput closed. Exiting.\n";
                            return 0;
                        }
                        cin.clear();
                        cin.ignore(numeric_limits<streamsize>::max(), '\n');
                        cout << "Invalid choice!\n";
                        continue;
                    }

                    if (c == 1)
                        app.registerStudent();
                    else if (c == 2)
                        app.listExams();
                    else if (c == 3)
                        app.listSlots();
                    else if (c == 4)
                        app.bookSlot();
                    else if (c == 5)
                        app.myBookings();
                    else if (c == 6)
                        app.cancelBooking();
                    else if (c != 0)
                        cout << "Invalid choice!\n";
                }
            } else if (role == 2) {
                int c = -1;
                while (c != 0) {
                    cout << "\n--- ADMIN MENU ---\n";
                    cout << "1 Add exam + priority\n";
                    cout << "2 Add slot\n";
                    cout << "3 Add lab\n";
                    cout << "4 Add computer (bulk)\n";
                    cout << "5 View labs\n";
                    cout << "6 View students\n";
                    cout << "7 View bookings\n";
                    cout << "8 Run Priority+FCFS scheduler\n";
                    cout << "9 View PC availability by slot\n";
                    cout << "10 Complete session\n";
                    cout << "11 Deadlock cycle detection demo\n";
                    cout << "0 Back\n";
                    cout << "Choice: ";

                    c = -1;
                    if (!(cin >> c)) {
                        if (cin.eof()) {
                            cout << "\nInput closed. Exiting.\n";
                            return 0;
                        }
                        cin.clear();
                        cin.ignore(numeric_limits<streamsize>::max(), '\n');
                        cout << "Invalid choice!\n";
                        continue;
                    }

                    if (c == 1)
                        app.addExam();
                    else if (c == 2)
                        app.addSlot();
                    else if (c == 3)
                        app.addLab();
                    else if (c == 4)
                        app.addComputer();
                    else if (c == 5)
                        app.listLabs();
                    else if (c == 6)
                        app.listStudents();
                    else if (c == 7)
                        app.listBookings();
                    else if (c == 8)
                        app.runScheduler();
                    else if (c == 9)
                        app.computerAvailability();
                    else if (c == 10)
                        app.completeSession();
                    else if (c == 11) {
                        // Demonstration graph: process P1 waits for P2, P2 waits for P3.
                        // Adding P3 -> P1 creates a wait-for cycle (deadlock).
                        std::vector<std::vector<int>> waits={{1},{2},{}};
                        bool cycle=DeadlockPrevention::wouldCreateCycle(waits,2,0);
                        cout << "Wait-for graph: P1 -> P2 -> P3 -> P1\n";
                        cout << (cycle ? "DEADLOCK DETECTED: cycle found. Avoid the new wait edge.\n"
                                       : "No deadlock cycle found.\n");
                    }
                    else if (c != 0)
                        cout << "Invalid choice!\n";
                }
            } else if (role != 0) {
                cout << "Invalid role choice!\n";
            }
        }
    } catch (sql::SQLException& e) {
        cerr << "\nMySQL Fatal Error (Code " << e.getErrorCode() << "): " << e.what() << endl;
        return 1;
    } catch (const exception& e) {
        cerr << "\nUnexpected Error: " << e.what() << endl;
        return 1;
    }


    cout << "\nLabSync closed successfully.\n";
    return 0;
}
