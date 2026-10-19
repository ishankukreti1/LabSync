# LabSync — Smart Lab Scheduling System

LabSync is an OS–DBMS integrated project designed to manage examination slot bookings, computer laboratory allocation, and scheduling through a centralized system.

## Features

- Student registration and login
- Student and administrator dashboards
- Exam creation and slot management
- Exam booking and cancellation
- Priority-based and First-Come, First-Served (FCFS) scheduling
- Automatic lab and computer allocation
- Duplicate booking prevention
- Transaction-based resource allocation
- Deadlock handling mechanisms

## Technology Stack

| Component | Technology |
|---|---|
| Frontend | HTML, CSS, JavaScript |
| Web Backend | Python Flask |
| Core Scheduling Engine | C++17 |
| Database | MySQL |
| Build System | CMake |

## System Workflow

1. Students register and log in.
2. Administrators create exams and available slots.
3. Students submit exam booking requests.
4. The scheduler processes requests based on priority and arrival order.
5. Available lab computers are allocated to eligible requests.
6. Booking and allocation details are stored in MySQL.
7. Students and administrators view updated results through their dashboards.

## Project Structure

- `app.py` — Flask application and web routes
- `config.py` — Application configuration
- `database.py` — Python database connectivity
- `main.cpp` — C++ console application entry point
- `scheduler_bridge.cpp` — Integration with the C++ scheduling engine
- `src/` — Core C++ implementation
- `include/` — C++ header files
- `database/` — Database schema
- `templates/` — HTML templates
- `static/` — CSS, icons and other static resources

## Team Members

- Ishan Kukreti
- Krish Joshi
- Anubhav Singh Negi

## Academic Project

**Course:** Operating Systems and Database Management Systems

**Project:** LabSync — Smart Lab Scheduling System