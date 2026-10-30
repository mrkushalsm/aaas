#ifndef AAAS_VIRTUAL_TRANSPORT_POOL_H
#define AAAS_VIRTUAL_TRANSPORT_POOL_H

#include <cstddef>
#include <vector>

// Caller serializes access to the readiness/use vectors.
inline int reserveVirtualTransport(const std::vector<bool>& ready,
                                   std::vector<bool>& used) {
    if (ready.size() != used.size()) return -1;
    for (size_t i = 0; i < ready.size(); ++i) {
        if (ready[i] && !used[i]) {
            used[i] = true;
            return static_cast<int>(i);
        }
    }
    return -1;
}

inline bool releaseVirtualTransport(std::vector<bool>& used, int slot) {
    if (slot < 0 || static_cast<size_t>(slot) >= used.size() || !used[slot]) return false;
    used[slot] = false;
    return true;
}

#endif
