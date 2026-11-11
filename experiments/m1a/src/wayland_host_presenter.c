#include "gpu_presenter.h"
#include "resize_generation.h"

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
            "  --socket <path>     UNIX domain socket path (default: $XDG_RUNTIME_DIR/aaas-wayland.sock)\n"
            "  --title <title>     Wayland window title (default: 'AaaS Android 16 Desktop')\n"
            "  --app-id <id>       Wayland toplevel application identity\n"
            "  --defer-map         Keep an unassigned dynamic slot hidden until it receives an app identity\n"
            "  --width <w>         Initial window width (default: 1280)\n"
            "  --height <h>        Initial window height (default: 720)\n"
            "  --display-width <w> Initial Android source width\n"
            "  --display-height <h> Initial Android source height\n"
            "  --node <path>       DRM render node selected by Wayland feedback (or AAAS_DRM_RENDER_NODE)\n"
            "  --implicit-sync     Force implicit synchronization\n"
            "  --software-shm-test  Test-only wl_shm backend; requires memfd frame inputs\n"
            "  --test-reconnect-on-producer-close  Test persistent toplevel recovery\n"
            "  --frames <N>        Exit after presenting N frames (default: 0 = infinite)\n"
            "  --exit-on-close     Exit after the first client window closes\n"
            "  --input-socket <p>  Private pointer input socket (SEQPACKET)\n"
            "  --input-session <id> 64-bit input session identity\n"
            "  --input-display-id-file <p> Android target display ID file\n"
            "  --resize-request <p>  Session-local Android display resize request\n"
            "  --identity-request <p> Update the app window title and desktop identity\n"
            "  --identity-ack <p>     Acknowledge the applied window identity\n"
            "  --trace-buffer-identities  Log DMA-BUF backing identity transitions\n"
            "  --trace-staging-stages  Log per-operation staging timing and thread CPU data\n"
            "  --trace-input-response-roi x,y,w,h  Track a small visible region after pointer input\n"
            "  --help              Show this help message\n",
            prog);
}

int main(int argc, char **argv) {
    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);
    signal(SIGHUP, SIG_IGN);

    char default_socket_path[sizeof(((struct sockaddr_un *)0)->sun_path)];
    const char *socket_path = NULL;
    const char *title = "AaaS Android 16 Desktop";
    const char *app_id = "org.aaas.android";
    bool defer_map = false;
    uint32_t width = 1280;
    uint32_t height = 720;
    uint32_t display_width = 0;
    uint32_t display_height = 0;
    const char *drm_node = getenv("AAAS_DRM_RENDER_NODE");
    bool force_implicit = false;
    bool software_shm_test = false;
    bool test_reconnect_on_producer_close = false;
    bool trace_buffer_identities = false;
    bool trace_staging_stages = false;
    bool trace_input_roi = false;
    uint32_t input_roi_x = 0, input_roi_y = 0, input_roi_width = 0, input_roi_height = 0;
    uint32_t max_frames = 0;
    bool exit_on_close = false;
    const char *input_socket_path = NULL;
    uint64_t input_session_id = 0;
    const char *input_display_id_file = NULL;
    const char *resize_request_path = NULL;
    const char *identity_request_path = NULL;
    const char *identity_ack_path = NULL;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--socket") == 0 && i + 1 < argc) {
            socket_path = argv[++i];
        } else if (strcmp(argv[i], "--title") == 0 && i + 1 < argc) {
            title = argv[++i];
        } else if (strcmp(argv[i], "--app-id") == 0 && i + 1 < argc) {
            app_id = argv[++i];
        } else if (strcmp(argv[i], "--defer-map") == 0) {
            defer_map = true;
        } else if (strcmp(argv[i], "--width") == 0 && i + 1 < argc) {
            width = (uint32_t)strtoul(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--height") == 0 && i + 1 < argc) {
            height = (uint32_t)strtoul(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--display-width") == 0 && i + 1 < argc) {
            display_width = (uint32_t)strtoul(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--display-height") == 0 && i + 1 < argc) {
            display_height = (uint32_t)strtoul(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--node") == 0 && i + 1 < argc) {
            drm_node = argv[++i];
        } else if (strcmp(argv[i], "--implicit-sync") == 0) {
            force_implicit = true;
        } else if (strcmp(argv[i], "--software-shm-test") == 0) {
            software_shm_test = true;
        } else if (strcmp(argv[i], "--test-reconnect-on-producer-close") == 0) {
            test_reconnect_on_producer_close = true;
        } else if (strcmp(argv[i], "--frames") == 0 && i + 1 < argc) {
            max_frames = (uint32_t)strtoul(argv[++i], NULL, 10);
        } else if (strcmp(argv[i], "--exit-on-close") == 0) {
            exit_on_close = true;
        } else if (strcmp(argv[i], "--input-socket") == 0 && i + 1 < argc) {
            input_socket_path = argv[++i];
        } else if (strcmp(argv[i], "--input-session") == 0 && i + 1 < argc) {
            input_session_id = strtoull(argv[++i], NULL, 0);
        } else if (strcmp(argv[i], "--input-display-id-file") == 0 && i + 1 < argc) {
            input_display_id_file = argv[++i];
        } else if (strcmp(argv[i], "--resize-request") == 0 && i + 1 < argc) {
            resize_request_path = argv[++i];
        } else if (strcmp(argv[i], "--identity-request") == 0 && i + 1 < argc) {
            identity_request_path = argv[++i];
        } else if (strcmp(argv[i], "--identity-ack") == 0 && i + 1 < argc) {
            identity_ack_path = argv[++i];
        } else if (strcmp(argv[i], "--trace-buffer-identities") == 0) {
            trace_buffer_identities = true;
        } else if (strcmp(argv[i], "--trace-staging-stages") == 0) {
            trace_staging_stages = true;
        } else if (strcmp(argv[i], "--trace-input-response-roi") == 0 && i + 1 < argc) {
            char extra = '\0';
            if (sscanf(argv[++i], "%u,%u,%u,%u%c", &input_roi_x, &input_roi_y,
                       &input_roi_width, &input_roi_height, &extra) != 4 ||
                input_roi_width == 0 || input_roi_height == 0) {
                fprintf(stderr, "Invalid input response ROI; expected x,y,w,h\n");
                return 1;
            }
            trace_input_roi = true;
            trace_staging_stages = true;
            trace_buffer_identities = true;
        } else if (strcmp(argv[i], "--help") == 0) {
            print_usage(argv[0]);
            return 0;
        } else {
            fprintf(stderr, "Unknown option: %s\n", argv[i]);
            print_usage(argv[0]);
            return 1;
        }
    }

    if (input_socket_path && input_session_id == 0) {
        fprintf(stderr, "[AaaS Presenter] --input-socket requires --input-session\n");
        return 1;
    }

    if (!socket_path) {
        const char *runtime_dir = getenv("XDG_RUNTIME_DIR");
        if (!runtime_dir || runtime_dir[0] != '/') {
            fprintf(stderr, "XDG_RUNTIME_DIR must name an absolute user runtime directory, or pass --socket\n");
            return 1;
        }
        int n = snprintf(default_socket_path, sizeof(default_socket_path),
                         "%s/aaas-wayland.sock", runtime_dir);
        if (n < 0 || (size_t)n >= sizeof(default_socket_path)) {
            fprintf(stderr, "default Wayland socket path exceeds the UNIX socket path limit; pass --socket\n");
            return 1;
        }
        socket_path = default_socket_path;
    }
    if (!software_shm_test && (!drm_node || !*drm_node)) {
        fprintf(stderr, "No DRM render node selected; pass --node or set AAAS_DRM_RENDER_NODE from host capability discovery\n");
        return 1;
    }
    if (strlen(socket_path) >= sizeof(((struct sockaddr_un *)0)->sun_path)) {
        fprintf(stderr, "Frame socket path exceeds the UNIX socket path limit; pass a shorter --socket path\n");
        return 1;
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
    memcpy(addr.sun_path, socket_path, strlen(socket_path) + 1);

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

    int input_server_sock = -1;
    if (input_socket_path) {
        if (strcmp(input_socket_path, socket_path) == 0) {
            fprintf(stderr, "[AaaS Presenter] input and frame sockets must differ\n");
            close(server_sock);
            unlink(socket_path);
            return 2;
        }
        input_server_sock = socket(AF_UNIX,
                                   SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
        if (input_server_sock < 0) {
            perror("[AaaS Presenter] input socket failed");
            close(server_sock);
            unlink(socket_path);
            return 2;
        }
        unlink(input_socket_path);
        struct sockaddr_un input_addr;
        memset(&input_addr, 0, sizeof(input_addr));
        input_addr.sun_family = AF_UNIX;
        strncpy(input_addr.sun_path, input_socket_path,
                sizeof(input_addr.sun_path) - 1);
        if (bind(input_server_sock, (struct sockaddr *)&input_addr,
                 sizeof(input_addr)) < 0) {
            perror("[AaaS Presenter] input bind failed");
            close(input_server_sock);
            close(server_sock);
            unlink(socket_path);
            return 2;
        }
        chmod(input_socket_path, 0660);
        if (listen(input_server_sock, 4) < 0) {
            perror("[AaaS Presenter] input listen failed");
            close(input_server_sock);
            unlink(input_socket_path);
            close(server_sock);
            unlink(socket_path);
            return 2;
        }
        printf("[AaaS Presenter] Input listening on %s (session=%016llx)\n",
               input_socket_path, (unsigned long long)input_session_id);
        fflush(stdout);
    }

    while (g_running) {
        int client_sock = accept(server_sock, NULL, NULL);
        if (client_sock < 0) {
            if (errno == EINTR) continue;
            perror("[AaaS Presenter] accept failed");
            break;
        }

        printf("[AaaS Presenter] Android container connected! (client_fd=%d)\n", client_sock);
        fflush(stdout);

        aaas_resize_resume_state resume =
            aaas_read_resize_resume_state(resize_request_path);
        aaas_presenter_config cfg = {
            .sock = client_sock,
            .producer_listen_fd = server_sock,
            .initial_generation = resume.generation,
            .title = title,
            .app_id = app_id,
            .defer_map = defer_map,
            .initial_width = width,
            .initial_height = height,
            .initial_display_width = display_width,
            .initial_display_height = display_height,
            .drm_node = drm_node,
            .software_shm_test = software_shm_test,
            .test_reconnect_on_producer_close =
                test_reconnect_on_producer_close,
            .force_implicit_sync = force_implicit,
            .trace_buffer_identities = trace_buffer_identities,
            .trace_staging_stages = trace_staging_stages,
            .trace_input_roi = trace_input_roi,
            .input_roi_x = input_roi_x,
            .input_roi_y = input_roi_y,
            .input_roi_width = input_roi_width,
            .input_roi_height = input_roi_height,
            .max_frames = max_frames,
            .running = &g_running,
            .input_listen_fd = input_server_sock,
            .input_session_id = input_session_id,
            .input_display_id_file = input_display_id_file,
            .resize_request_path = resize_request_path,
            .identity_request_path = identity_request_path,
            .identity_ack_path = identity_ack_path,
        };

        if (cfg.initial_generation > 0) {
            cfg.initial_display_width = resume.width;
            cfg.initial_display_height = resume.height;
            cfg.initial_width = resume.width;
            cfg.initial_height = resume.height;
            printf("[AaaS Presenter] Resuming resize state after %u at %ux%u\n",
                   cfg.initial_generation, resume.width, resume.height);
            fflush(stdout);
        }

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
    if (input_server_sock >= 0) {
        close(input_server_sock);
        unlink(input_socket_path);
    }
    printf("[AaaS Presenter] Clean shutdown complete.\n");
    return 0;
}
