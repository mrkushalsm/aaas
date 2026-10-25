#pragma once

#include <sys/cdefs.h>
#include <stddef.h>

__BEGIN_DECLS

typedef struct native_handle {
    int version;        /* sizeof(native_handle_t) */
    int numFds;         /* number of file-descriptors at &data[0] */
    int numInts;        /* number of ints at &data[numFds] */
    int data[0];        /* numFds + numInts ints */
} native_handle_t;

typedef const native_handle_t* buffer_handle_t;

native_handle_t* native_handle_create(int numFds, int numInts);
native_handle_t* native_handle_clone(const native_handle_t* handle);
int native_handle_close(const native_handle_t* h);
int native_handle_delete(native_handle_t* h);

__END_DECLS
