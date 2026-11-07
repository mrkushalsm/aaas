/*
 * Copyright (C) 2026 AaaS contributors
 * SPDX-License-Identifier: MIT
 *
 * Session-local legacy ashmem creation compatibility for the Android HIDL
 * audio adapter. Back the shared region with a CLOEXEC memfd so the HIDL FMQ
 * can operate without exposing /dev/ashmem to the container.
 */
#define MFD_CLOEXEC 0x0001u
#define MFD_NOEXEC_SEAL 0x0008u
#define F_ADD_SEALS 1033
#define F_GET_SEALS 1034
#define F_SEAL_SHRINK 0x0002
#define F_SEAL_GROW 0x0004
#define F_SEAL_FUTURE_WRITE 0x0010
#define PROT_WRITE 0x2

extern int *__errno(void);

static long call_syscall3(long number, long a1, long a2, long a3) {
    long result;
    __asm__ volatile("syscall"
        : "=a"(result)
        : "a"(number), "D"(a1), "S"(a2), "d"(a3)
        : "rcx", "r11", "memory");
    return result;
}

int ashmem_create_region(const char *name, unsigned long size) {
    if (size > (unsigned long)0x7fffffffffffffffULL) {
        *__errno() = 22;
        return -1;
    }
    long fd = call_syscall3(319, (long)name, MFD_CLOEXEC | MFD_NOEXEC_SEAL, 0);
    if (fd < 0) {
        *__errno() = (int)-fd;
        return -1;
    }
    long status = call_syscall3(77, fd, (long)size, 0);
    if (status < 0) {
        (void)call_syscall3(3, fd, 0, 0);
        *__errno() = (int)-status;
        return -1;
    }
    status = call_syscall3(72, fd, F_ADD_SEALS,
                           F_SEAL_GROW | F_SEAL_SHRINK);
    if (status < 0) {
        (void)call_syscall3(3, fd, 0, 0);
        *__errno() = (int)-status;
        return -1;
    }
    return (int)fd;
}

int ashmem_set_prot_region(int fd, int prot) {
    long seals = call_syscall3(72, fd, F_GET_SEALS, 0);
    if (seals < 0) {
        *__errno() = (int)-seals;
        return -1;
    }
    if (prot & PROT_WRITE) {
        if (seals & F_SEAL_FUTURE_WRITE) {
            *__errno() = 22;
            return -1;
        }
        return 0;
    }
    long status = call_syscall3(72, fd, F_ADD_SEALS, F_SEAL_FUTURE_WRITE);
    if (status < 0) {
        *__errno() = (int)-status;
        return -1;
    }
    return 0;
}

int ashmem_valid(int fd) {
    long status = call_syscall3(72, fd, F_GET_SEALS, 0);
    return status >= 0;
}

static int pin_compat(int fd) {
    if (ashmem_valid(fd)) return 0;
    *__errno() = 25;
    return -1;
}

int ashmem_pin_region(int fd, unsigned long offset, unsigned long length) {
    (void)offset;
    (void)length;
    return pin_compat(fd);
}

int ashmem_unpin_region(int fd, unsigned long offset, unsigned long length) {
    (void)offset;
    (void)length;
    return pin_compat(fd);
}

int ashmem_get_size_region(int fd) {
    long current = call_syscall3(8, fd, 0, 1); /* lseek(fd, 0, SEEK_CUR) */
    if (current < 0) {
        *__errno() = (int)-current;
        return -1;
    }
    long size = call_syscall3(8, fd, 0, 2); /* lseek(fd, 0, SEEK_END) */
    if (size < 0) {
        *__errno() = (int)-size;
        return -1;
    }
    long restored = call_syscall3(8, fd, current, 0); /* SEEK_SET */
    if (restored < 0) {
        *__errno() = (int)-restored;
        return -1;
    }
    if (size > 0x7fffffffL) {
        *__errno() = 75;
        return -1;
    }
    return (int)size;
}
