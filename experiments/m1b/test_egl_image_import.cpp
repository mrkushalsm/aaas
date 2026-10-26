#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <dlfcn.h>
#include <drm/drm.h>

#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <GLES2/gl2ext.h>

#include <vndk/hardware_buffer.h>
#include <cutils/native_handle.h>

#define AAAS_MAGIC 0x61616173
#define TEST_WIDTH 64
#define TEST_HEIGHT 64

#ifndef EGL_NATIVE_BUFFER_ANDROID
#define EGL_NATIVE_BUFFER_ANDROID 0x3140
#endif

typedef void* EGLImageKHR;
typedef void* GLeglImageOES;

extern "C" {
    EGLClientBuffer eglGetNativeClientBufferANDROID(const struct AHardwareBuffer *buffer);
    EGLImageKHR eglCreateImageKHR(EGLDisplay dpy, EGLContext ctx, EGLenum target, EGLClientBuffer buffer, const EGLint *attrib_list);
    EGLBoolean eglDestroyImageKHR(EGLDisplay dpy, EGLImageKHR image);
}

extern "C" {
    void __libc_init(void* raw_args, void* onexit, int (*main_fn)(int, char**, char**), void* structors);
    int* __errno();
    int* __errno_location() { return __errno(); }
}

int main(int argc, char** argv, char** envp);

__attribute__((naked))
extern "C" void _start() {
    __asm__ volatile (
        "xor %ebp, %ebp\n"
        "mov %rsp, %rdi\n"
        "and $-16, %rsp\n"
        "sub $48, %rsp\n"
        "movq $0, (%rsp)\n"
        "movq $0, 8(%rsp)\n"
        "movq $0, 16(%rsp)\n"
        "movq $0, 24(%rsp)\n"
        "movq $0, 32(%rsp)\n"
        "movq $0, 40(%rsp)\n"
        "xor %esi, %esi\n"
        "lea main(%rip), %rdx\n"
        "mov %rsp, %rcx\n"
        "call __libc_init\n"
        "hlt\n"
    );
}

typedef void (*PFN_glEGLImageTargetTexture2DOES)(GLenum target, GLeglImageOES image);

int main(int argc, char** argv, char** envp) {
    printf("========================================================\n");
    printf("[EGL_TEST] Starting Independent Graphics Import Test\n");
    printf("========================================================\n");

    // 1. Allocate a real hardware DMA-BUF via DRM
    int drm_fd = open("/dev/dri/renderD129", O_RDWR | O_CLOEXEC);
    if (drm_fd < 0) {
        drm_fd = open("/dev/dri/renderD128", O_RDWR | O_CLOEXEC);
    }
    if (drm_fd < 0) {
        printf("[EGL_TEST] FAIL: Failed to open DRM render node: %s\n", strerror(errno));
        return 1;
    }
    printf("[EGL_TEST] 1. Opened DRM device (fd=%d)\n", drm_fd);

    uint32_t width = TEST_WIDTH;
    uint32_t height = TEST_HEIGHT;
    uint32_t stride = (width + 31) & ~31;
    uint32_t bpp = 4;
    uint32_t size = stride * height * bpp;

    int dma_buf_fd = -1;
    struct {
        uint64_t size;
        uint32_t handle;
        uint32_t pad;
    } gem_create = { .size = size };

    // Try i915 GEM create first
    if (ioctl(drm_fd, 0xc010645b, &gem_create) == 0 && gem_create.handle > 0) {
        struct drm_prime_handle prime = {};
        prime.handle = gem_create.handle;
        prime.flags = DRM_CLOEXEC | DRM_RDWR;
        if (ioctl(drm_fd, DRM_IOCTL_PRIME_HANDLE_TO_FD, &prime) == 0) {
            dma_buf_fd = prime.fd;
            printf("[EGL_TEST] 1. Allocated Intel GPU DMA-BUF (fd=%d, size=%u)\n", dma_buf_fd, size);
        }
    }

    if (dma_buf_fd < 0) {
        // Fallback to DRM dumb buffer
        struct drm_mode_create_dumb dumb = {};
        dumb.width = stride;
        dumb.height = height;
        dumb.bpp = 32;
        if (ioctl(drm_fd, DRM_IOCTL_MODE_CREATE_DUMB, &dumb) == 0) {
            struct drm_prime_handle prime = {};
            prime.handle = dumb.handle;
            prime.flags = DRM_CLOEXEC | DRM_RDWR;
            if (ioctl(drm_fd, DRM_IOCTL_PRIME_HANDLE_TO_FD, &prime) == 0) {
                dma_buf_fd = prime.fd;
                printf("[EGL_TEST] 1. Allocated DRM Dumb DMA-BUF (fd=%d, size=%u)\n", dma_buf_fd, size);
            }
        }
    }

    if (dma_buf_fd < 0) {
        printf("[EGL_TEST] FAIL: DRM allocation failed\n");
        close(drm_fd);
        return 2;
    }

    uint64_t usage = AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE |
                     AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN |
                     AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN;

    // 2. Construct native_handle_t
    native_handle_t* nh = native_handle_create(1, 10);
    nh->data[0] = dma_buf_fd;
    nh->data[1] = AAAS_MAGIC;
    nh->data[2] = width;
    nh->data[3] = height;
    nh->data[4] = stride;
    nh->data[5] = AHARDWAREBUFFER_FORMAT_R8G8B8A8_UNORM;
    nh->data[6] = (int)(usage & 0xffffffff); // usage low
    nh->data[7] = (int)(usage >> 32);        // usage high
    nh->data[8] = size;
    nh->data[9] = 101; // buffer id low
    nh->data[10] = 0;  // buffer id high
    printf("[EGL_TEST] 2. Created native_handle_t (fd=%d, %dx%d, stride=%d)\n", dma_buf_fd, width, height, stride);

    // 3. Construct AHardwareBuffer
    AHardwareBuffer_Desc desc = {};
    desc.width = width;
    desc.height = height;
    desc.layers = 1;
    desc.format = AHARDWAREBUFFER_FORMAT_R8G8B8A8_UNORM;
    desc.usage = usage;
    desc.stride = stride;

    AHardwareBuffer* ahb = nullptr;
    int err = AHardwareBuffer_createFromHandle(&desc, nh, AHARDWAREBUFFER_CREATE_FROM_HANDLE_METHOD_CLONE, &ahb);
    printf("[EGL_TEST] 3. AHardwareBuffer_createFromHandle ret=%d, ahb=%p\n", err, ahb);
    if (err != 0 || !ahb) {
        printf("[EGL_TEST] FAIL: AHardwareBuffer_createFromHandle failed (%d)\n", err);
        return 3;
    }

    // 4. Initialize EGL and GLES context
    EGLDisplay dpy = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    printf("[EGL_TEST] 4. eglGetDisplay ret=%p\n", dpy);
    if (dpy == EGL_NO_DISPLAY) {
        printf("[EGL_TEST] FAIL: eglGetDisplay failed\n");
        return 4;
    }

    EGLint major = 0, minor = 0;
    if (!eglInitialize(dpy, &major, &minor)) {
        printf("[EGL_TEST] FAIL: eglInitialize failed\n");
        return 5;
    }
    printf("[EGL_TEST] 4. eglInitialize succeeded: version %d.%d\n", major, minor);

    const char* client_exts = eglQueryString(dpy, EGL_EXTENSIONS);
    printf("[EGL_TEST] 4. EGL Extensions contains EGL_ANDROID_image_native_buffer: %s\n",
           strstr(client_exts ? client_exts : "", "EGL_ANDROID_image_native_buffer") ? "YES" : "NO");

    EGLint configAttribs[] = {
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
        EGL_RED_SIZE, 8,
        EGL_GREEN_SIZE, 8,
        EGL_BLUE_SIZE, 8,
        EGL_ALPHA_SIZE, 8,
        EGL_NONE
    };
    EGLConfig config;
    EGLint numConfigs = 0;
    eglChooseConfig(dpy, configAttribs, &config, 1, &numConfigs);

    EGLint contextAttribs[] = {
        EGL_CONTEXT_CLIENT_VERSION, 2,
        EGL_NONE
    };
    EGLContext ctx = eglCreateContext(dpy, config, EGL_NO_CONTEXT, contextAttribs);
    if (ctx == EGL_NO_CONTEXT) {
        printf("[EGL_TEST] FAIL: eglCreateContext failed (0x%x)\n", eglGetError());
        return 6;
    }

    EGLint pbufferAttribs[] = {
        EGL_WIDTH, 16,
        EGL_HEIGHT, 16,
        EGL_NONE
    };
    EGLSurface pbuf = eglCreatePbufferSurface(dpy, config, pbufferAttribs);
    if (!eglMakeCurrent(dpy, pbuf, pbuf, ctx)) {
        printf("[EGL_TEST] FAIL: eglMakeCurrent failed (0x%x)\n", eglGetError());
        return 7;
    }
    printf("[EGL_TEST] 4. EGL context made current! GL_VENDOR=%s, GL_RENDERER=%s\n",
           glGetString(GL_VENDOR), glGetString(GL_RENDERER));

    // 5. Create EGLImage from Android Hardware Buffer
    EGLClientBuffer clientBuffer = eglGetNativeClientBufferANDROID(ahb);
    if (!clientBuffer) {
        clientBuffer = (EGLClientBuffer)ahb;
    }
    printf("[EGL_TEST] 5. Creating EGLImage from clientBuffer=%p...\n", clientBuffer);

    EGLint imageAttribs[] = {
        EGL_IMAGE_PRESERVED_KHR, EGL_TRUE,
        EGL_NONE
    };
    EGLImageKHR img = eglCreateImageKHR(dpy, EGL_NO_CONTEXT, EGL_NATIVE_BUFFER_ANDROID, clientBuffer, imageAttribs);
    if (img == EGL_NO_IMAGE_KHR) {
        printf("[EGL_TEST] FAIL: eglCreateImageKHR failed with error 0x%x\n", eglGetError());
        return 8;
    }
    printf("[EGL_TEST] 5. SUCCESS: eglCreateImageKHR succeeded! image=%p\n", img);

    // 6. Bind to texture and render known color into FBO
    PFN_glEGLImageTargetTexture2DOES glEGLImageTargetTexture2DOES_fn =
        (PFN_glEGLImageTargetTexture2DOES)eglGetProcAddress("glEGLImageTargetTexture2DOES");
    if (!glEGLImageTargetTexture2DOES_fn) {
        printf("[EGL_TEST] FAIL: glEGLImageTargetTexture2DOES not found\n");
        return 9;
    }

    GLuint tex = 0;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glEGLImageTargetTexture2DOES_fn(GL_TEXTURE_2D, (GLeglImageOES)img);

    GLuint fbo = 0;
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);

    GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
    printf("[EGL_TEST] 6. glCheckFramebufferStatus = 0x%x (COMPLETE=0x%x)\n", status, GL_FRAMEBUFFER_COMPLETE);
    if (status != GL_FRAMEBUFFER_COMPLETE) {
        printf("[EGL_TEST] FAIL: Framebuffer incomplete\n");
        return 10;
    }

    glViewport(0, 0, width, height);
    // Render known distinct test color: Red=0.2 (51), Green=0.4 (102), Blue=0.8 (204), Alpha=1.0 (255)
    glClearColor(0.2f, 0.4f, 0.8f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glFinish();
    printf("[EGL_TEST] 6. Rendered test pattern (R=0.2, G=0.4, B=0.8, A=1.0) and flushed\n");

    // 7. Validate output via glReadPixels
    uint32_t gl_pixel = 0;
    glReadPixels(width / 2, height / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, &gl_pixel);
    uint8_t gl_r = (gl_pixel) & 0xff;
    uint8_t gl_g = (gl_pixel >> 8) & 0xff;
    uint8_t gl_b = (gl_pixel >> 16) & 0xff;
    uint8_t gl_a = (gl_pixel >> 24) & 0xff;
    printf("[EGL_TEST] 7. glReadPixels center pixel: RGBA(%u, %u, %u, %u) [0x%08x]\n",
           gl_r, gl_g, gl_b, gl_a, gl_pixel);

    // 8. Validate output via CPU mmap on DMA-BUF
    void* cpu_ptr = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, dma_buf_fd, 0);
    if (cpu_ptr == MAP_FAILED) {
        printf("[EGL_TEST] FAIL: Failed to mmap DMA-BUF fd=%d: %s\n", dma_buf_fd, strerror(errno));
        return 11;
    }

    uint32_t* dma_pixels = (uint32_t*)cpu_ptr;
    uint32_t dma_pixel = dma_pixels[(height / 2) * stride + (width / 2)];
    uint8_t dma_r = (dma_pixel) & 0xff;
    uint8_t dma_g = (dma_pixel >> 8) & 0xff;
    uint8_t dma_b = (dma_pixel >> 16) & 0xff;
    uint8_t dma_a = (dma_pixel >> 24) & 0xff;
    printf("[EGL_TEST] 8. DMA-BUF mmap center pixel: RGBA(%u, %u, %u, %u) [0x%08x]\n",
           dma_r, dma_g, dma_b, dma_a, dma_pixel);

    // Allow small rounding tolerance (+/- 2)
    int diff_r = abs((int)dma_r - 51);
    int diff_g = abs((int)dma_g - 102);
    int diff_b = abs((int)dma_b - 204);
    int diff_a = abs((int)dma_a - 255);

    if (diff_r <= 2 && diff_g <= 2 && diff_b <= 2 && diff_a <= 2) {
        printf("[EGL_TEST] >>> SUCCESS: DMA-BUF pixel contents match rendered test pattern perfectly! <<<\n");
    } else {
        printf("[EGL_TEST] FAIL: Pixel mismatch! Expected ~(51, 102, 204, 255), got (%u, %u, %u, %u)\n",
               dma_r, dma_g, dma_b, dma_a);
        return 12;
    }

    // 9. Cleanup
    munmap(cpu_ptr, size);
    glDeleteFramebuffers(1, &fbo);
    glDeleteTextures(1, &tex);
    eglDestroyImageKHR(dpy, img);
    eglDestroySurface(dpy, pbuf);
    eglDestroyContext(dpy, ctx);
    eglTerminate(dpy);
    AHardwareBuffer_release(ahb);
    native_handle_close(nh);
    native_handle_delete(nh);
    close(dma_buf_fd);
    close(drm_fd);

    printf("[EGL_TEST] 9. Cleaned up all resources without error!\n");
    printf("========================================================\n");
    printf("[EGL_TEST] INDEPENDENT GRAPHICS IMPORT TEST: PASSED\n");
    printf("========================================================\n");
    return 0;
}
