#include "gpu_presenter.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <errno.h>

static volatile sig_atomic_t g_running = 1;
static void handle_signal(int sig) {
    (void)sig;
    g_running = 0;
}

static void print_usage(const char *prog) {
    fprintf(stderr,
            "Usage: %s [options]\n"
            "Options:\n"
            "  --socket <path>     UNIX domain socket path (default: /run/media/mrkus/Homework/aaas-workspace/tmp/aaas_wayland.sock)\n"
            "  --title <title>     Wayland window title (default: 'AaaS Android 16 Desktop')\n"
            "  --width <w>         Initial window width (default: 1280)\n"
            "  --height <h>        Initial window height (default: 720)\n"
            "  --node <path>       DRM render node path (default: /dev/dri/renderD129)\n"
            "  --implicit-sync     Force implicit synchronization\n"
            "  --frames <N>        Exit after presenting N frames (default: 0 = infinite)\n"
            "  --exit-on-close     Exit after the first client window closes\n"
            "  --help              Show this help message\n",
            prog);
}

int main(int argc, char **argv) {
    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);
    signal(SIGHUP, SIG_IGN);

    const char *socket_path = "/run/media/mrkus/Homework/aaas-workspace/tmp/aaas_ipc/wayland.sock";
    const char *title = "AaaS Android 16 Desktop";
    uint32_t width = 1280;
    uint32_t height = 720;
    const char *drm_node = "/dev/dri/renderD129";
    bool force_implicit = false;
    uint32_t max_frames = 0;
    bool exit_on_close = false;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--socket") == 0 && i + 1 < argc) {
            socket_path = argv[++i];
        } else if (strcmp(argv[i], "--title") == 0 && i + 1 < argc) {
            title = argv[++i];
        } else if (strcmp(argv[i], "--width") == 0 && i + 1 < argc) {
            width = (uint32_t)strtoul(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--height") == 0 && i + 1 < argc) {
            height = (uint32_t)strtoul(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--node") == 0 && i + 1 < argc) {
            drm_node = argv[++i];
        } else if (strcmp(argv[i], "--implicit-sync") == 0) {
            force_implicit = true;
        } else if (strcmp(argv[i], "--frames") == 0 && i + 1 < argc) {
            max_frames = (uint32_t)strtoul(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--exit-on-close") == 0) {
            exit_on_close = true;
        } else if (strcmp(argv[i], "--help") == 0) {
            print_usage(argv[0]);
            return 0;
        } else {
            fprintf(stderr, "Unknown option: %s\n", argv[i]);
            print_usage(argv[0]);
            return 1;
        }
    }

    int server_sock = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
    if (server_sock < 0) {
        perror("[AaaS Presenter] socket failed");
        return 2;
    }

    unlink(socket_path);

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, socket_path, sizeof(addr.sun_path) - 1);

    if (bind(server_sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("[AaaS Presenter] bind failed");
        close(server_sock);
        return 2;
    }

    chmod(socket_path, 0777);

    if (listen(server_sock, 1) < 0) {
        perror("[AaaS Presenter] listen failed");
        close(server_sock);
        unlink(socket_path);
        return 2;
    }

    printf("[AaaS Presenter] Server listening on %s (SEQPACKET)\n", socket_path);
    printf("[AaaS Presenter] Waiting for Android container connection...\n");
    fflush(stdout);

    while (g_running) {
        int client_sock = accept(server_sock, NULL, NULL);
        if (client_sock < 0) {
            if (errno == EINTR) continue;
            perror("[AaaS Presenter] accept failed");
            break;
        }

        printf("[AaaS Presenter] Android container connected! (client_fd=%d)\n", client_sock);
        fflush(stdout);

        aaas_presenter_config cfg = {
            .sock = client_sock,
            .title = title,
            .initial_width = width,
            .initial_height = height,
            .drm_node = drm_node,
            .force_implicit_sync = force_implicit,
            .max_frames = max_frames,
            .running = &g_running,
        };

        int ret = aaas_run_gpu_presenter(&cfg);
        printf("[AaaS Presenter] Presenter run finished with code %d\n", ret);
        close(client_sock);

        if (max_frames > 0 || exit_on_close || !g_running) {
            break;
        }
        printf("[AaaS Presenter] Ready for next connection...\n");
        fflush(stdout);
    }

    close(server_sock);
    unlink(socket_path);
    printf("[AaaS Presenter] Clean shutdown complete.\n");
    return 0;
}
