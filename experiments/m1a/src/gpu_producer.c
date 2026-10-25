#include "gpu_producer.h"
#include "wire_v2.h"
#include "sync_util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <poll.h>
#include <errno.h>
#include <time.h>
#include <math.h>

#include <gbm.h>
#include <drm_fourcc.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <GLES2/gl2ext.h>

static void log_producer_event(const char *event, uint32_t gen, uint32_t id,
                               const char *extra_json) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    uint64_t t_ns = (uint64_t)t.tv_sec * 1000000000ULL + (uint64_t)t.tv_nsec;
    if (extra_json && *extra_json) {
        fprintf(stderr, "{\"t_ns\":%llu,\"role\":\"producer\",\"event\":\"%s\","
                        "\"generation\":%u,\"id\":%u,%s}\n",
                (unsigned long long)t_ns, event, gen, id, extra_json);
    } else {
        fprintf(stderr, "{\"t_ns\":%llu,\"role\":\"producer\",\"event\":\"%s\","
                        "\"generation\":%u,\"id\":%u}\n",
                (unsigned long long)t_ns, event, gen, id);
    }
}

typedef struct {
    struct gbm_bo *bo;
    EGLImageKHR image;
    GLuint rbo;
    GLuint fbo;
    uint32_t id;
    uint32_t gen;
    int busy;
    int release_fence_fd;
} gpu_buffer;

static const char *vert_shader_src =
    "attribute vec2 position;\n"
    "varying vec2 v_pos;\n"
    "void main() {\n"
    "    v_pos = position;\n"
    "    gl_Position = vec4(position, 0.0, 1.0);\n"
    "}\n";

static const char *frag_shader_src =
    "precision mediump float;\n"
    "varying vec2 v_pos;\n"
    "uniform float u_time;\n"
    "void main() {\n"
    "    float dist = length(v_pos);\n"
    "    float angle = atan(v_pos.y, v_pos.x) + u_time;\n"
    "    float r = 0.5 + 0.5 * sin(angle * 3.0 + u_time);\n"
    "    float g = 0.5 + 0.5 * sin(angle * 5.0 - u_time * 1.5);\n"
    "    float b = 0.5 + 0.5 * cos(dist * 10.0 - u_time * 2.0);\n"
    "    // Add pulsating border\n"
    "    if (abs(v_pos.x) > 0.95 || abs(v_pos.y) > 0.95) {\n"
    "        r = 1.0; g = 1.0; b = 1.0;\n"
    "    }\n"
    "    gl_FragColor = vec4(r, g, b, 1.0);\n"
    "}\n";

static GLuint compile_shader(GLenum type, const char *src) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char buf[512];
        glGetShaderInfoLog(s, sizeof(buf), NULL, buf);
        fprintf(stderr, "Shader compile error: %s\n", buf);
        glDeleteShader(s);
        return 0;
    }
    return s;
}

static GLuint create_program(void) {
    GLuint vs = compile_shader(GL_VERTEX_SHADER, vert_shader_src);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, frag_shader_src);
    if (!vs || !fs) return 0;
    GLuint p = glCreateProgram();
    glAttachShader(p, vs);
    glAttachShader(p, fs);
    glBindAttribLocation(p, 0, "position");
    glLinkProgram(p);
    glDeleteShader(vs);
    glDeleteShader(fs);
    GLint ok = 0;
    glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) {
        char buf[512];
        glGetProgramInfoLog(p, sizeof(buf), NULL, buf);
        fprintf(stderr, "Program link error: %s\n", buf);
        glDeleteProgram(p);
        return 0;
    }
    return p;
}

int aaas_run_gpu_producer(const aaas_producer_config *config) {
    const char *node = config->drm_node ? config->drm_node : "/dev/dri/renderD129";
    int devfd = open(node, O_RDWR | O_CLOEXEC);
    if (devfd < 0) {
        // Fallback to renderD128 if renderD129 not openable
        node = "/dev/dri/renderD128";
        devfd = open(node, O_RDWR | O_CLOEXEC);
        if (devfd < 0) {
            perror("open render node");
            return 2;
        }
    }

    struct gbm_device *gbm = gbm_create_device(devfd);
    if (!gbm) {
        perror("gbm_create_device");
        close(devfd);
        return 2;
    }

    EGLDisplay dpy = EGL_NO_DISPLAY;
    EGLContext ctx = EGL_NO_CONTEXT;
    PFNEGLCREATEIMAGEKHRPROC create_image = NULL;
    PFNEGLDESTROYIMAGEKHRPROC destroy_image = NULL;
    PFNGLEGLIMAGETARGETRENDERBUFFERSTORAGEOESPROC image_target_rbo = NULL;
    PFNEGLCREATESYNCKHRPROC create_sync = NULL;
    PFNEGLDUPNATIVEFENCEFDANDROIDPROC dup_fence = NULL;
    PFNEGLDESTROYSYNCKHRPROC destroy_sync = NULL;

    GLuint prog = 0;
    GLint u_time_loc = -1;

    if (!config->cpu_fallback) {
        PFNEGLGETPLATFORMDISPLAYEXTPROC get_platform_display =
            (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
        if (get_platform_display) {
            dpy = get_platform_display(EGL_PLATFORM_GBM_KHR, gbm, NULL);
        }
        if (dpy == EGL_NO_DISPLAY) {
            dpy = eglGetDisplay((EGLNativeDisplayType)gbm);
        }
        if (!eglInitialize(dpy, NULL, NULL)) {
            fprintf(stderr, "eglInitialize failed\n");
            gbm_device_destroy(gbm);
            close(devfd);
            return 2;
        }

        eglBindAPI(EGL_OPENGL_ES_API);
        static const EGLint ctx_attribs[] = {
            EGL_CONTEXT_CLIENT_VERSION, 2,
            EGL_NONE
        };
        ctx = eglCreateContext(dpy, EGL_NO_CONFIG_KHR, EGL_NO_CONTEXT, ctx_attribs);
        if (ctx == EGL_NO_CONTEXT) {
            fprintf(stderr, "eglCreateContext failed: 0x%x\n", eglGetError());
            eglTerminate(dpy);
            gbm_device_destroy(gbm);
            close(devfd);
            return 2;
        }

        if (!eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx)) {
            fprintf(stderr, "eglMakeCurrent failed: 0x%x\n", eglGetError());
            eglDestroyContext(dpy, ctx);
            eglTerminate(dpy);
            gbm_device_destroy(gbm);
            close(devfd);
            return 2;
        }

        create_image = (PFNEGLCREATEIMAGEKHRPROC)eglGetProcAddress("eglCreateImageKHR");
        destroy_image = (PFNEGLDESTROYIMAGEKHRPROC)eglGetProcAddress("eglDestroyImageKHR");
        image_target_rbo = (PFNGLEGLIMAGETARGETRENDERBUFFERSTORAGEOESPROC)eglGetProcAddress("glEGLImageTargetRenderbufferStorageOES");
        create_sync = (PFNEGLCREATESYNCKHRPROC)eglGetProcAddress("eglCreateSyncKHR");
        dup_fence = (PFNEGLDUPNATIVEFENCEFDANDROIDPROC)eglGetProcAddress("eglDupNativeFenceFDANDROID");
        destroy_sync = (PFNEGLDESTROYSYNCKHRPROC)eglGetProcAddress("eglDestroySyncKHR");

        prog = create_program();
        if (!prog) {
            fprintf(stderr, "Failed to create GPU shader program\n");
            return 2;
        }
        u_time_loc = glGetUniformLocation(prog, "u_time");

        log_producer_event("gpu_initialized", 0, 0,
            "\"renderer\":\"GLES2\",\"fence_extension\":\"EGL_ANDROID_native_fence_sync\"");
    } else {
        log_producer_event("cpu_initialized", 0, 0, "\"mode\":\"cpu_fallback_baseline\"");
    }

    gpu_buffer buffers[AAAS_PRODUCER_NUM_BUFFERS] = {0};
    for (int i = 0; i < AAAS_PRODUCER_NUM_BUFFERS; i++) {
        buffers[i].release_fence_fd = -1;
    }

    uint32_t gen = 0, w = 0, h = 0, next_id = 1, frame_idx = 0;
    int running = 1;

    static const GLfloat quad_vertices[] = {
        -1.0f, -1.0f,
         1.0f, -1.0f,
        -1.0f,  1.0f,
         1.0f,  1.0f,
    };

    while (running) {
        if (config->max_frames > 0 && frame_idx >= config->max_frames) {
            break;
        }

        struct pollfd p = { .fd = config->sock, .events = POLLIN };
        int pr = poll(&p, 1, 16);
        if (pr < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if (p.revents & (POLLHUP | POLLERR)) {
            log_producer_event("presenter_disconnect", gen, 0, NULL);
            break;
        }

        if (p.revents & POLLIN) {
            aaas_v2_msg m;
            int fds[AAAS_V2_MAX_FDS];
            unsigned nfds = 0;
            int r = aaas_v2_recv(config->sock, &m, fds, &nfds);
            if (r <= 0) {
                log_producer_event("presenter_disconnect", gen, 0, NULL);
                break;
            }

            if (m.type == AAAS_V2_RESIZE && m.generation > gen &&
                m.width && m.height && m.width <= AAAS_V2_MAX_DIM && m.height <= AAAS_V2_MAX_DIM) {
                // Resize event: destroy unbusy buffers
                for (int i = 0; i < AAAS_PRODUCER_NUM_BUFFERS; i++) {
                    if (buffers[i].bo && !buffers[i].busy) {
                        if (buffers[i].fbo) glDeleteFramebuffers(1, &buffers[i].fbo);
                        if (buffers[i].rbo) glDeleteRenderbuffers(1, &buffers[i].rbo);
                        if (buffers[i].image && destroy_image) destroy_image(dpy, buffers[i].image);
                        gbm_bo_destroy(buffers[i].bo);
                        if (buffers[i].release_fence_fd >= 0) close(buffers[i].release_fence_fd);
                        buffers[i] = (gpu_buffer){ .release_fence_fd = -1 };
                    }
                }
                gen = m.generation;
                w = m.width;
                h = m.height;
                char extra[64];
                snprintf(extra, sizeof(extra), "\"width\":%u,\"height\":%u", w, h);
                log_producer_event("resize", gen, 0, extra);
            } else if (m.type == AAAS_V2_RELEASE) {
                // Buffer release notification from presenter
                int found = 0;
                for (int i = 0; i < AAAS_PRODUCER_NUM_BUFFERS; i++) {
                    if (buffers[i].id == m.id && buffers[i].gen == m.generation && buffers[i].busy) {
                        buffers[i].busy = 0;
                        if (nfds > 0 && fds[0] >= 0) {
                            if (buffers[i].release_fence_fd >= 0) {
                                close(buffers[i].release_fence_fd);
                            }
                            buffers[i].release_fence_fd = fds[0];
                            log_producer_event("release_with_fence", m.generation, m.id, "\"fence\":\"received\"");
                        } else {
                            log_producer_event("release", m.generation, m.id, "\"fence\":\"none\"");
                        }
                        found = 1;
                        break;
                    }
                }
                if (!found && nfds > 0) {
                    close(fds[0]);
                }
            } else if (m.type == AAAS_V2_CLOSE) {
                log_producer_event("close_received", gen, 0, NULL);
                break;
            }
        }

        if (!gen || !w || !h) {
            continue;
        }

        // Find an idle buffer slot
        int slot = -1;
        for (int i = 0; i < AAAS_PRODUCER_NUM_BUFFERS; i++) {
            if (!buffers[i].busy) {
                slot = i;
                break;
            }
        }
        if (slot < 0) {
            // All buffers currently busy; wait for a release
            continue;
        }

        // Check if buffer dimensions match current generation
        if (buffers[slot].bo && buffers[slot].gen != gen) {
            if (buffers[slot].fbo) glDeleteFramebuffers(1, &buffers[slot].fbo);
            if (buffers[slot].rbo) glDeleteRenderbuffers(1, &buffers[slot].rbo);
            if (buffers[slot].image && destroy_image) destroy_image(dpy, buffers[slot].image);
            gbm_bo_destroy(buffers[slot].bo);
            if (buffers[slot].release_fence_fd >= 0) close(buffers[slot].release_fence_fd);
            buffers[slot] = (gpu_buffer){ .release_fence_fd = -1 };
        }

        // Allocate buffer if needed
        if (!buffers[slot].bo) {
            uint32_t usage = GBM_BO_USE_RENDERING;
            if (config->cpu_fallback) usage |= GBM_BO_USE_LINEAR;
            buffers[slot].bo = gbm_bo_create(gbm, w, h, GBM_FORMAT_XRGB8888, usage);
            if (!buffers[slot].bo) {
                log_producer_event("gbm_alloc_failed", gen, 0, NULL);
                break;
            }
            buffers[slot].id = next_id++;
            buffers[slot].gen = gen;

            if (!config->cpu_fallback) {
                buffers[slot].image = create_image(dpy, EGL_NO_CONTEXT,
                                                   EGL_NATIVE_PIXMAP_KHR,
                                                   buffers[slot].bo, NULL);
                if (buffers[slot].image == EGL_NO_IMAGE_KHR) {
                    log_producer_event("egl_image_failed", gen, buffers[slot].id, NULL);
                    break;
                }
                glGenRenderbuffers(1, &buffers[slot].rbo);
                glBindRenderbuffer(GL_RENDERBUFFER, buffers[slot].rbo);
                image_target_rbo(GL_RENDERBUFFER, buffers[slot].image);

                glGenFramebuffers(1, &buffers[slot].fbo);
                glBindFramebuffer(GL_FRAMEBUFFER, buffers[slot].fbo);
                glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                          GL_RENDERBUFFER, buffers[slot].rbo);

                if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
                    log_producer_event("fbo_incomplete", gen, buffers[slot].id, NULL);
                    break;
                }
            }
        }

        // Safe buffer reuse: wait on release fence if presenter provided one
        if (buffers[slot].release_fence_fd >= 0) {
            int wait_res = sync_file_wait(buffers[slot].release_fence_fd, 1000);
            char wait_extra[64];
            snprintf(wait_extra, sizeof(wait_extra), "\"release_wait_result\":%d", wait_res);
            log_producer_event("release_fence_waited", gen, buffers[slot].id, wait_extra);
            close(buffers[slot].release_fence_fd);
            buffers[slot].release_fence_fd = -1;
        }

        int acquire_fence_fd = -1;

        if (!config->cpu_fallback) {
            // Genuine GPU rendering pipeline
            glBindFramebuffer(GL_FRAMEBUFFER, buffers[slot].fbo);
            glViewport(0, 0, w, h);

            glUseProgram(prog);
            float time_val = (float)frame_idx * 0.05f;
            glUniform1f(u_time_loc, time_val);

            glEnableVertexAttribArray(0);
            glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, quad_vertices);
            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
            glDisableVertexAttribArray(0);

            // Export acquire fence via EGL_ANDROID_native_fence_sync
            if (create_sync && dup_fence) {
                EGLSyncKHR sync = create_sync(dpy, EGL_SYNC_NATIVE_FENCE_ANDROID, NULL);
                glFlush(); // dispatch GPU commands to ring
                acquire_fence_fd = dup_fence(dpy, sync);
                destroy_sync(dpy, sync);
            } else {
                glFlush();
            }
        } else {
            // CPU fallback baseline
            uint32_t stride = 0;
            void *mapdata = NULL;
            void *px = gbm_bo_map(buffers[slot].bo, 0, 0, w, h,
                                  GBM_BO_TRANSFER_WRITE, &stride, &mapdata);
            if (px) {
                for (uint32_t y = 0; y < h; y++) {
                    uint32_t *row = (uint32_t *)((char *)px + y * stride);
                    for (uint32_t x = 0; x < w; x++) {
                        row[x] = ((x + frame_idx * 3) & 255) << 16 |
                                 ((y + frame_idx * 2) & 255) << 8 |
                                 ((frame_idx * 7) & 255);
                    }
                }
                gbm_bo_unmap(buffers[slot].bo, mapdata);
            }
        }

        // Export DMA-BUF FD
        int dma_fd = gbm_bo_get_fd(buffers[slot].bo);
        if (dma_fd < 0) {
            log_producer_event("dmabuf_export_failed", gen, buffers[slot].id, NULL);
            if (acquire_fence_fd >= 0) close(acquire_fence_fd);
            break;
        }

        aaas_v2_msg m = {
            .magic = AAAS_V2_MAGIC,
            .version = AAAS_V2_VERSION,
            .type = AAAS_V2_BUFFER,
            .flags = (acquire_fence_fd >= 0 ? AAAS_V2_FLAG_EXPLICIT_SYNC : 0) |
                     (config->cpu_fallback ? AAAS_V2_FLAG_LINEAR : 0),
            .generation = gen,
            .id = buffers[slot].id,
            .width = w,
            .height = h,
            .format = DRM_FORMAT_XRGB8888,
            .num_planes = 1,
            .modifier = gbm_bo_get_modifier(buffers[slot].bo),
            .offset = { gbm_bo_get_offset(buffers[slot].bo, 0) },
            .stride = { gbm_bo_get_stride(buffers[slot].bo) },
        };

        int send_fds[2];
        unsigned send_nfds = 1;
        send_fds[0] = dma_fd;
        if (acquire_fence_fd >= 0) {
            send_fds[1] = acquire_fence_fd;
            send_nfds = 2;
        }

        int s_res = aaas_v2_send(config->sock, &m, send_fds, send_nfds);
        close(dma_fd);
        if (acquire_fence_fd >= 0) close(acquire_fence_fd);

        if (s_res != 0) {
            perror("send buffer");
            break;
        }

        buffers[slot].busy = 1;
        frame_idx++;

        char extra[128];
        snprintf(extra, sizeof(extra),
                 "\"frame\":%u,\"modifier\":%llu,\"explicit_sync\":%s",
                 frame_idx, (unsigned long long)m.modifier,
                 (m.flags & AAAS_V2_FLAG_EXPLICIT_SYNC) ? "true" : "false");
        log_producer_event(config->cpu_fallback ? "frame_sent_cpu" : "frame_sent_gpu",
                           gen, buffers[slot].id, extra);

        struct timespec delay = { .tv_nsec = 16666666 }; /* ~60 fps */
        nanosleep(&delay, NULL);
    }

    // Teardown
    for (int i = 0; i < AAAS_PRODUCER_NUM_BUFFERS; i++) {
        if (buffers[i].fbo) glDeleteFramebuffers(1, &buffers[i].fbo);
        if (buffers[i].rbo) glDeleteRenderbuffers(1, &buffers[i].rbo);
        if (buffers[i].image && destroy_image) destroy_image(dpy, buffers[i].image);
        if (buffers[i].bo) gbm_bo_destroy(buffers[i].bo);
        if (buffers[i].release_fence_fd >= 0) close(buffers[i].release_fence_fd);
    }
    if (prog) glDeleteProgram(prog);
    if (ctx != EGL_NO_CONTEXT) {
        eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
        eglDestroyContext(dpy, ctx);
    }
    if (dpy != EGL_NO_DISPLAY) eglTerminate(dpy);
    if (gbm) gbm_device_destroy(gbm);
    close(devfd);

    return 0;
}
