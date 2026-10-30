#include "../virtual_transport_pool.h"

#include <cstdio>
#include <cstdlib>

static void require(bool condition, const char* message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

int main() {
    std::vector<bool> ready{true, true};
    std::vector<bool> used{false, false};
    const int first = reserveVirtualTransport(ready, used);
    const int second = reserveVirtualTransport(ready, used);
    require(first == 0 && second == 1, "two displays receive different transport slots");
    require(reserveVirtualTransport(ready, used) == -1, "capacity rejects a third display");
    require(releaseVirtualTransport(used, first), "release first display transport");
    const int reused = reserveVirtualTransport(ready, used);
    require(reused == first, "released transport slot can be reused");
    require(releaseVirtualTransport(used, reused), "release reused transport slot");
    require(!releaseVirtualTransport(used, reused), "double release is rejected");

    std::vector<bool> partial_ready{true, false};
    std::vector<bool> partial_used{false, false};
    require(reserveVirtualTransport(partial_ready, partial_used) == 0,
            "only connected output is assignable");
    require(reserveVirtualTransport(partial_ready, partial_used) == -1,
            "unavailable endpoint is never assigned");
    std::vector<bool> mismatched_used{false};
    require(reserveVirtualTransport(ready, mismatched_used) == -1,
            "mismatched pool state is rejected");

    std::puts("virtual transport pool tests passed; independent assignment and reuse verified");
    return 0;
}
