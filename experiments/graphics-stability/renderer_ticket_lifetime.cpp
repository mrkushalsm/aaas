// Deterministic contract test for the Marl ticket sequence used by
// swiftshader/src/Device/Renderer.cpp (DrawCall::run / synchronize).
// It models a mapped render-target allocation with an explicit live bit. The
// negative control observes an invalid unmap order without dereferencing an
// invalid pointer or risking a process crash.

#include <marl/ticket.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <iostream>
#include <mutex>
#include <thread>

namespace {

using namespace std::chrono_literals;

struct Gate {
	std::mutex mutex;
	std::condition_variable changed;
	bool entered = false;
	bool proceed = false;

	bool waitForEntry() {
		std::unique_lock<std::mutex> lock(mutex);
		return changed.wait_for(lock, 2s, [&] { return entered; });
	}

	void blockWorker() {
		std::unique_lock<std::mutex> lock(mutex);
		entered = true;
		changed.notify_all();
		if(!changed.wait_for(lock, 2s, [&] { return proceed; })) {
			std::abort();
		}
	}

	void releaseWorker() {
		std::lock_guard<std::mutex> lock(mutex);
		proceed = true;
		changed.notify_all();
	}
};

bool validRetirementWaitsForWorker() {
	marl::Ticket::Queue drawTickets;
	auto drawTicket = drawTickets.take();
	std::atomic<bool> mapped{true};
	std::atomic<bool> invalidAccess{false};
	std::atomic<uint32_t> pixel{0xA55A1234};
	Gate gate;

	std::thread worker([&] {
		gate.blockWorker();
		if(!mapped.load(std::memory_order_acquire)) {
			invalidAccess.store(true, std::memory_order_release);
		} else {
			(void)pixel.load(std::memory_order_relaxed);
		}
		drawTicket.done(); // DrawCall::teardown completes its draw ticket.
	});
	if(!gate.waitForEntry()) {
		gate.releaseWorker();
		worker.join();
		return false;
	}

	std::atomic<bool> syncStarted{false};
	std::atomic<bool> syncReturned{false};
	std::thread synchronizer([&] {
		auto syncTicket = drawTickets.take(); // Renderer::synchronize()
		syncStarted.store(true, std::memory_order_release);
		syncTicket.wait();
		syncReturned.store(true, std::memory_order_release);
		syncTicket.done();
	});

	const auto deadline = std::chrono::steady_clock::now() + 2s;
	while(!syncStarted.load(std::memory_order_acquire) &&
	      std::chrono::steady_clock::now() < deadline) {
		std::this_thread::yield();
	}
	std::this_thread::sleep_for(30ms);
	const bool blockedWhileJobInFlight =
	    syncStarted.load(std::memory_order_acquire) &&
	    !syncReturned.load(std::memory_order_acquire) &&
	    mapped.load(std::memory_order_acquire);

	gate.releaseWorker();
	worker.join();
	synchronizer.join();
	const bool completedBeforeUnmap = syncReturned.load(std::memory_order_acquire) &&
	                                  !invalidAccess.load(std::memory_order_acquire);
	mapped.store(false, std::memory_order_release); // caller retires after sync
	return blockedWhileJobInFlight && completedBeforeUnmap;
}

bool negativeControlDetectsPrematureUnmap() {
	marl::Ticket::Queue drawTickets;
	auto drawTicket = drawTickets.take();
	std::atomic<bool> mapped{true};
	std::atomic<bool> invalidAccess{false};
	Gate gate;
	std::thread worker([&] {
		gate.blockWorker();
		// The guard represents the diagnostic's pre-access lifetime check.
		// It records the violation and intentionally avoids touching dead memory.
		if(!mapped.load(std::memory_order_acquire)) {
			invalidAccess.store(true, std::memory_order_release);
		}
		drawTicket.done();
	});
	if(!gate.waitForEntry()) {
		gate.releaseWorker();
		worker.join();
		return false;
	}

	mapped.store(false, std::memory_order_release); // intentionally invalid order
	gate.releaseWorker();
	worker.join();
	return invalidAccess.load(std::memory_order_acquire);
}

} // namespace

int main() {
	const bool valid = validRetirementWaitsForWorker();
	const bool negative = negativeControlDetectsPrematureUnmap();
	std::cout << "valid_inflight_wait=" << (valid ? "PASS" : "FAIL") << '\n';
	std::cout << "premature_unmap_negative_control="
	          << (negative ? "DETECTED" : "MISSED") << '\n';
	return valid && negative ? 0 : 1;
}
