#pragma once
#include <vector>
#include "Models.h"
class Scheduler { public: static std::vector<BookingRequest> priorityFCFS(std::vector<BookingRequest> q); };
