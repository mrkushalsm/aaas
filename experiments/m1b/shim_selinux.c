 /* Freestanding shim for Android 16 shared-kernel container */

extern void *malloc(unsigned long size);

static char *alloc_context(const char *src) {
    unsigned long len = 0;
    while (src[len]) len++;
    char *p = (char *)malloc(len + 1);
    if (!p) return 0;
    for (unsigned long i = 0; i <= len; i++) {
        p[i] = src[i];
    }
    return p;
}

int is_selinux_enabled(void) { return 0; }
int is_selinux_mls_enabled(void) { return 0; }
int security_getenforce(void) { return 0; }
int security_setenforce(int value) { return 0; }

int selinux_status_open(int fallback) { return 0; }
int selinux_status_updated(void) { return 0; }

int getcon(char **con) { if (con) *con = alloc_context("u:r:init:s0"); return 0; }
int setcon(const char *con) { return 0; }
int getpidcon(int pid, char **con) { if (con) *con = alloc_context("u:r:init:s0"); return 0; }
int getprevcon(char **con) { if (con) *con = alloc_context("u:r:init:s0"); return 0; }
int getpeercon(int fd, char **con) { if (con) *con = alloc_context("u:r:init:s0"); return 0; }

static int is_staging_path(const char *path) {
    if (!path) return 0;
    for (int i = 0; path[i]; i++) {
        if (path[i] == 'a' && path[i+1] == 'p' && path[i+2] == 'e' && path[i+3] == 'x') {
            return 1;
        }
    }
    return 0;
}

int getfilecon(const char *path, char **con) {
    if (con) *con = alloc_context(is_staging_path(path) ? "u:object_r:staging_data_file:s0" : "u:object_r:system_file:s0");
    return 0;
}
int lgetfilecon(const char *path, char **con) {
    if (con) *con = alloc_context(is_staging_path(path) ? "u:object_r:staging_data_file:s0" : "u:object_r:system_file:s0");
    return 0;
}
int setfilecon(const char *path, const char *con) { return 0; }
int lsetfilecon(const char *path, const char *con) { return 0; }

int selabel_lookup(void *handle, char **con, const char *key, int type) {
    if (con) *con = alloc_context(is_staging_path(key) ? "u:object_r:staging_data_file:s0" : "u:object_r:system_file:s0");
    return 0;
}
int selabel_lookup_best_match(void *handle, char **con, const char *key, const char **aliases, int type) {
    if (con) *con = alloc_context(is_staging_path(key) ? "u:object_r:staging_data_file:s0" : "u:object_r:system_file:s0");
    return 0;
}

int security_compute_create(const char *scon, const char *tcon, unsigned short tclass, char **newcon) {
    if (newcon) *newcon = alloc_context("u:r:vendor_init:s0");
    return 0;
}

int setexeccon(const char *con) { return 0; }
int setsockcreatecon(const char *con) { return 0; }
int setfscreatecon(const char *con) { return 0; }
int setkeycreatecon(const char *con) { return 0; }

void freecon(char *con) {
    extern void free(void *ptr);
    if (con) free(con);
}

int selinux_check_access(const char *scon, const char *tcon, const char *tclass, const char *perm, void *auditdata) {
    return 0;
}

static int dummy_sehandle = 1;
void *selinux_android_file_context_handle(void) {
    return &dummy_sehandle;
}
void selinux_android_set_sehandle(void *hnd) {
    (void)hnd;
}
int selinux_android_setcontext(int uid, int is_system_server, const char *se_info, const char *nice_name) {
    return 0;
}
int selinux_android_setcon(const char *con) {
    return 0;
}
void *selinux_android_service_context_handle(void) {
    return &dummy_sehandle;
}
void *selinux_android_hw_service_context_handle(void) {
    return &dummy_sehandle;
}
void *selinux_android_vendor_service_context_handle(void) {
    return &dummy_sehandle;
}
void *selinux_android_keystore2_key_context_handle(void) {
    return &dummy_sehandle;
}
void *selinux_android_tee_service_context_handle(void) {
    return &dummy_sehandle;
}
int selinux_android_seapp_context_init(void) {
    return 0;
}
int selinux_android_restorecon(const char *file, unsigned int flags) {
    return 0;
}
int selinux_android_restorecon_pkgdir(const char *pkgdir, const char *seinfo, unsigned int uid, unsigned int flags) {
    return 0;
}
int selinux_android_load_policy(void) {
    return 0;
}


/* Intercept setsockopt to remap SO_RCVBUFFORCE (33) -> SO_RCVBUF (8) for unprivileged ueventd */
int setsockopt(int sockfd, int level, int optname, const void *optval, unsigned int optlen) {
    if (level == 1 && optname == 33) {
        optname = 8;
    }
    register long r10 __asm__("r10") = (long)optval;
    register long r8  __asm__("r8")  = (long)optlen;
    long ret;
    __asm__ volatile (
        "syscall"
        : "=a" (ret)
        : "a" (54), "D" (sockfd), "S" (level), "d" (optname), "r" (r10), "r" (r8)
        : "rcx", "r11", "memory"
    );
    if (ret < 0) {
        return -1;
    }
    return (int)ret;
}

/* Intercept mount to protect pre-staged /apex in container runtimes */
int mount(const char *source, const char *target, const char *filesystemtype, unsigned long mountflags, const void *data) {
    if (target) {
        if (target[0] == '/' && target[1] == 'a' && target[2] == 'p' && target[3] == 'e' && target[4] == 'x' &&
            (target[5] == '\0' || target[5] == '/')) {
            return 0; // Return success to allow init SetupMountNamespaces to succeed without wiping /apex
        }
        if (target[0] == '/' && target[1] == 'b' && target[2] == 'o' && target[3] == 'o' && target[4] == 't') {
            return 0;
        }
    }
    register long r10 __asm__("r10") = (long)mountflags;
    register long r8  __asm__("r8")  = (long)data;
    long ret;
    __asm__ volatile (
        "syscall"
        : "=a" (ret)
        : "a" (165), "D" (source), "S" (target), "d" (filesystemtype), "r" (r10), "r" (r8)
        : "rcx", "r11", "memory"
    );
    if (ret < 0) {
        return -1;
    }
    return (int)ret;
}

/* Intercept setpriority to tolerate lack of CAP_SYS_NICE in unprivileged containers */
int setpriority(int which, int who, int prio) {
    long ret;
    __asm__ volatile (
        "syscall"
        : "=a" (ret)
        : "a" (141), "D" (which), "S" (who), "d" (prio)
        : "rcx", "r11", "memory"
    );
    if (ret < 0) {
        return 0;
    }
    return (int)ret;
}

/* Freestanding ashmem replacement backed by Linux memfd_create */
int ashmem_create_region(const char *name, unsigned long size) {
    if (!name) name = "ashmem";
    long fd;
    __asm__ volatile (
        "syscall"
        : "=a" (fd)
        : "a" (319), "D" (name), "S" (3)
        : "rcx", "r11", "memory"
    );
    if (fd < 0) {
        return -1;
    }
    long ret;
    __asm__ volatile (
        "syscall"
        : "=a" (ret)
        : "a" (77), "D" ((int)fd), "S" (size)
        : "rcx", "r11", "memory"
    );
    if (ret < 0) {
        __asm__ volatile ("syscall" : : "a" (3), "D" ((int)fd) : "rcx", "r11", "memory");
        return -1;
    }
    return (int)fd;
}

int ashmem_set_prot_region(int fd, int prot) {
    return 0;
}

int ashmem_valid(int fd) {
    return 1;
}

int ashmem_pin_region(int fd, unsigned long offset, unsigned long len) {
    return 0;
}

int ashmem_unpin_region(int fd, unsigned long offset, unsigned long len) {
    return 0;
}


/* Intercept ioctl to strip FLAT_BINDER_FLAG_TXN_SECURITY_CTX (0x1000) from BINDER_SET_CONTEXT_MGR_EXT
 * on kernels lacking host SELinux, preventing LSM -EOPNOTSUPP transaction failures in rust_binder. */
extern int *__errno(void);
int ioctl(int fd, unsigned long request, void *arg) {
    if (request == 0x4018620d && arg) {
        unsigned int *flags = (unsigned int *)((char *)arg + 4);
        *flags &= ~0x1000;
    }
    long ret;
    __asm__ volatile (
        "syscall"
        : "=a" (ret)
        : "a" (16), "D" (fd), "S" (request), "d" (arg)
        : "rcx", "r11", "memory"
    );
    if (ret < 0) {
        if (__errno) *__errno() = (int)(-ret);
        return -1;
    }
    return (int)ret;
}




