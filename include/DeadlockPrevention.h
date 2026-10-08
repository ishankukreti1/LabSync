#pragma once
#include <vector>
class DeadlockPrevention { public: static bool wouldCreateCycle(const std::vector<std::vector<int>>& graph,int from,int to); };
