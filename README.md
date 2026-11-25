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
## Student chatbot

The student dashboard includes a support chatbot. It uses authenticated student context to retrieve that student's own bookings and public exam-slot information from MySQL. Without an AI key it provides deterministic local answers for supported intents.

To enable the generative AI response layer, set these environment variables before starting Flask:

```powershell
$env:OPENAI_API_KEY="your-api-key"
$env:OPENAI_MODEL="gpt-4o-mini"
# Optional for an OpenAI-compatible provider:
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
python app.py
```

Keep the API key server-side and out of source control. The model receives only public schedule data and the authenticated student's own booking records. It cannot execute SQL or modify bookings. If the provider is unavailable, LabSync falls back to local rule-based responses.

## Deadlock handling

The C++ scheduler uses a consistent transaction lock order (request, slot, lab rows ordered by ID, then selected computer) and handles MySQL deadlock error 1213 and lock-wait timeout 1205 by rolling back and retrying up to three attempts with bounded backoff. The scheduler reports detected deadlocks in its output. This is transaction-level deadlock recovery; the separate graph-cycle helper remains a utility and should not be described as monitoring MySQL's live wait-for graph.
