#include "DeadlockPrevention.h"
#include <functional>
bool DeadlockPrevention::wouldCreateCycle(const std::vector<std::vector<int>>& g,int from,int to){
 auto x=g; if(from<0||to<0||from>=int(x.size())||to>=int(x.size())) return true; x[from].push_back(to);
 std::vector<int> c(x.size()); std::function<bool(int)> dfs=[&](int u){c[u]=1;for(int v:x[u]){if(c[v]==1)return true;if(c[v]==0&&dfs(v))return true;}c[u]=2;return false;};
 for(int i=0;i<int(x.size());++i)if(c[i]==0&&dfs(i))return true; return false;
}
