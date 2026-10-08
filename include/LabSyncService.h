#pragma once
#include "Database.h"
#include <string>
class LabSyncService {
    Database& db;
public:
    explicit LabSyncService(Database& d):db(d){}
    void registerStudent(); void addExam(); void addSlot(); void addLab(); void addComputer();
    void listStudents(); void listExams(); void listSlots(); void bookSlot(); void myBookings(); void cancelBooking();
    void listBookings(); void runScheduler(); void computerAvailability(); void completeSession();
};
