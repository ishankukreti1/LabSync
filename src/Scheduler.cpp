#include "Scheduler.h"
#include <algorithm>
std::vector<BookingRequest> Scheduler::priorityFCFS(std::vector<BookingRequest> q){
 std::stable_sort(q.begin(),q.end(),[](const auto&a,const auto&b){ if(a.priority!=b.priority)return a.priority<b.priority; return a.requestTime<b.requestTime;}); return q;
}
