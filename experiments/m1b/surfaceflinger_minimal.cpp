#include <stdint.h>
#include <string.h>
#include <unistd.h>

extern "C" {
    void __libc_init(void* raw_args, void* onexit, int (*main_fn)(int, char**, char**), void* structors);

    void _ZN7android12ProcessState4selfEv(void* sp_out);
    void _ZN7android12ProcessState15startThreadPoolEv(void* this_ptr);
    void* _ZN7android14IPCThreadState4selfEv();
    void _ZN7android14IPCThreadState14joinThreadPoolEb(void* this_ptr, bool isMain);
    void _ZN7android21defaultServiceManagerEv(void* sp_out);
    void _ZN7android10IInterface8asBinderERKNS_2spIS0_EE(void* sp_binder_out, const void* sp_interface_in);
    void _ZN7android2os15IServiceManager11asInterfaceERKNS_2spINS_7IBinderEEE(void* sp_aidl_sm_out, const void* sp_binder_in);
    void _ZN7android7BBinderC1Ev(void* this_ptr);
    void _ZNK7android7RefBase9incStrongEPKv(const void* this_ptr, const void* id);
    void _ZN7android2os16BpServiceManager10addServiceERKNSt3__112basic_stringIcNS2_11char_traitsIcEENS2_9allocatorIcEEEERKNS_2spINS_7IBinderEEEbi(
        void* status_out, void* this_ptr, const void* name_str, const void* sp_binder, bool allowIsolated, int dumpPriority);
}

#include <fcntl.h>

static void log_str(const char* s) {
    int fd = open("/dev/kmsg", O_WRONLY);
    if (fd >= 0) {
        write(fd, "<6>", 3);
        size_t len = 0;
        while (s[len]) len++;
        write(fd, s, len);
        close(fd);
    }
}

static void log_hex(const char* label, uintptr_t val) {
    int fd = open("/dev/kmsg", O_WRONLY);
    if (fd >= 0) {
        char buf[80];
        size_t idx = 0;
        buf[idx++] = '<'; buf[idx++] = '6'; buf[idx++] = '>';
        while (label[idx - 3]) { buf[idx] = label[idx - 3]; idx++; }
        buf[idx++] = '0'; buf[idx++] = 'x';
        for (int i = 15; i >= 0; i--) {
            int nibble = (val >> (i * 4)) & 0xf;
            buf[idx++] = (nibble < 10) ? ('0' + nibble) : ('a' + nibble - 10);
        }
        buf[idx++] = '\n';
        write(fd, buf, idx);
        close(fd);
    }
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

static void make_std_string(char buf[24], const char* str) {
    for (int i = 0; i < 24; i++) buf[i] = 0;
    size_t len = 0;
    while (str[len]) len++;
    buf[0] = (char)(len << 1);
    for (size_t i = 0; i < len; i++) buf[i + 1] = str[i];
}

static char s_binder[256] __attribute__((aligned(16)));

#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdarg.h>

static void kmsg_printf(const char* fmt, ...) {
    char buf[512];
    va_list args;
    va_start(args, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    if (n > 0) {
        int fd = open("/dev/kmsg", O_WRONLY | O_APPEND);
        if (fd >= 0) {
            write(fd, buf, n);
            close(fd);
        }
    }
}

int main(int argc, char** argv, char** envp) {
    kmsg_printf("<6>[SF_MINIMAL] surfaceflinger_minimal starting\n");
    void* proc_sp[1] = { 0 };
    _ZN7android12ProcessState4selfEv(proc_sp);
    kmsg_printf("<6>[SF_MINIMAL] proc_sp = %p\n", proc_sp[0]);
    if (!proc_sp[0]) return 100;
    _ZN7android12ProcessState15startThreadPoolEv(proc_sp[0]);

    void* legacy_sm_sp[1] = { 0 };
    _ZN7android21defaultServiceManagerEv(legacy_sm_sp);
    kmsg_printf("<6>[SF_MINIMAL] legacy_sm_sp = %p\n", legacy_sm_sp[0]);
    if (!legacy_sm_sp[0]) return 101;

    void* sm_binder_sp[1] = { 0 };
    _ZN7android10IInterface8asBinderERKNS_2spIS0_EE(sm_binder_sp, legacy_sm_sp);
    kmsg_printf("<6>[SF_MINIMAL] sm_binder_sp = %p\n", sm_binder_sp[0]);
    if (!sm_binder_sp[0]) return 102;

    void* aidl_sm_sp[1] = { 0 };
    _ZN7android2os15IServiceManager11asInterfaceERKNS_2spINS_7IBinderEEE(aidl_sm_sp, sm_binder_sp);
    kmsg_printf("<6>[SF_MINIMAL] aidl_sm_sp = %p\n", aidl_sm_sp[0]);
    if (!aidl_sm_sp[0]) return 103;

    void* leg_vtable = *(void**)legacy_sm_sp[0];
    void* bnd_vtable = *(void**)sm_binder_sp[0];
    char big_buf[1024];
    int n = snprintf(big_buf, sizeof(big_buf),
        "<6>[SF_MINIMAL] leg=%p leg_vt=%p bnd=%p bnd_vt=%p\n",
        legacy_sm_sp[0], leg_vtable, sm_binder_sp[0], bnd_vtable);
    int fd = open("/dev/kmsg", O_WRONLY | O_APPEND);
    if (fd >= 0) {
        write(fd, big_buf, n);
        close(fd);
    }

    return 42;

    for (int i = 0; i < 256; i++) s_binder[i] = 0;
    _ZN7android7BBinderC1Ev(s_binder);
    void* refbase = (char*)s_binder + 0x18;
    _ZNK7android7RefBase9incStrongEPKv(refbase, s_binder);

    void* binder_sp[1] = { s_binder };
    char status_out[128];

    char str_sf[24];
    make_std_string(str_sf, "SurfaceFlinger");
    for (int i = 0; i < 128; i++) status_out[i] = 0;
    _ZN7android2os16BpServiceManager10addServiceERKNSt3__112basic_stringIcNS2_11char_traitsIcEENS2_9allocatorIcEEEERKNS_2spINS_7IBinderEEEbi(
        status_out, aidl_sm_sp[0], str_sf, binder_sp, false, 0);

    char str_sf_aidl[24];
    make_std_string(str_sf_aidl, "SurfaceFlingerAIDL");
    for (int i = 0; i < 128; i++) status_out[i] = 0;
    _ZN7android2os16BpServiceManager10addServiceERKNSt3__112basic_stringIcNS2_11char_traitsIcEENS2_9allocatorIcEEEERKNS_2spINS_7IBinderEEEbi(
        status_out, aidl_sm_sp[0], str_sf_aidl, binder_sp, false, 0);

    void* ipc = _ZN7android14IPCThreadState4selfEv();
    if (ipc) {
        _ZN7android14IPCThreadState14joinThreadPoolEb(ipc, true);
    }
    return 0;
}
