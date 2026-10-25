#ifndef AAAS_WIRE_H
#define AAAS_WIRE_H
#include <stdint.h>
#define AAAS_MAGIC 0x53414141u
#define AAAS_VERSION 1u
#define AAAS_MAX_FDS 4
#define AAAS_MAX_DIM 8192u
enum { AAAS_HELLO=1, AAAS_BUFFER=2, AAAS_RELEASE=3, AAAS_RESIZE=4, AAAS_CLOSE=5 };
typedef struct {
 uint32_t magic, version, type, generation, id, width, height, format;
 uint64_t modifier;
 uint32_t stride, offset, flags, reserved;
} aaas_msg;
int aaas_send(int sock, const aaas_msg *msg, const int *fds, unsigned nfds);
int aaas_recv(int sock, aaas_msg *msg, int *fds, unsigned *nfds);
#endif
