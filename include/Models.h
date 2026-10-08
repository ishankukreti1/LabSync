#pragma once
#include <string>

struct Student {
    int id{};
    std::string name, email;
};

struct Exam {
    int id{};
    int priority{2}; // 1=High, 2=Normal, 3=Low; chosen by admin
    std::string name, subjectCode, date;
};

struct Slot {
    int id{}, examId{}, capacity{};
    std::string startTime, endTime;
};

struct BookingRequest {
    int id{}, studentId{}, examId{}, slotId{}, priority{3};
    std::string requestTime, status;
};

struct Computer {
    int id{}, labId{};
    std::string number, status;
};
