#include "gpu_producer.h"
#include "gpu_presenter.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/wait.h>

static volatile sig_atomic_t g_running = 1;
static void handle_signal(int sig) {
    (void)sig;
    g_running = 0;
}

static void print_usage(const char *prog) {
    fprintf(stderr,
            "Usage: %s [options]\n"
            "Options:\n"
            "  --node <path>       DRM render node path (default: /dev/dri/renderD129)\n"
            "  --cpu               Use CPU fallback rendering baseline\n"
            "  --implicit-sync     Force implicit synchronization (disable DRM syncobj)\n"
            "  --frames <N>        Exit after presenting N frames (default: infinite)\n"
            "  --help              Show this help message\n",
            prog);
}

int main(int argc, char **argv) {
    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);

    const char *drm_node = "/dev/dri/renderD129";
    bool cpu_fallback = false;
    bool force_implicit = false;
    uint32_t max_frames = 0;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--node") == 0 && i + 1 < argc) {
            drm_node = argv[++i];
        } else if (strcmp(argv[i], "--cpu") == 0) {
            cpu_fallback = true;
        } else if (strcmp(argv[i], "--implicit-sync") == 0) {
            force_implicit = true;
        } else if (strcmp(argv[i], "--frames") == 0 && i + 1 < argc) {
            max_frames = (uint32_t)strtoul(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--help") == 0) {
            print_usage(argv[0]);
            return 0;
        } else {
            fprintf(stderr, "Unknown option: %s\n", argv[i]);
            print_usage(argv[0]);
            return 1;
        }
    }

    int socks[2];
    if (socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, socks) != 0) {
        perror("socketpair");
        return 2;
    }

    pid_t child = fork();
    if (child < 0) {
        perror("fork");
        return 2;
    }

    if (child == 0) {
        // Child: Producer
        close(socks[0]);
        aaas_producer_config p_cfg = {
            .sock = socks[1],
            .drm_node = drm_node,
            .cpu_fallback = cpu_fallback,
            .max_frames = max_frames,
        };
        int ret = aaas_run_gpu_producer(&p_cfg);
        close(socks[1]);
        _exit(ret);
    }

    // Parent: Presenter
    close(socks[1]);
    aaas_presenter_config pres_cfg = {
        .sock = socks[0],
        .title = cpu_fallback ? "AaaS M1A.1 CPU Fallback Baseline" :
                                "AaaS M1A.1 Explicit Sync GPU Presenter",
        .initial_width = 640,
        .initial_height = 480,
        .drm_node = drm_node,
        .force_implicit_sync = force_implicit || cpu_fallback,
        .max_frames = max_frames,
        .input_listen_fd = -1,
        .input_session_id = 0,
    };
    int ret = aaas_run_gpu_presenter(&pres_cfg);
    close(socks[0]);

    // Ensure child process is terminated cleanly
    kill(child, SIGTERM);
    int status = 0;
    waitpid(child, &status, 0);

    return ret;
}
