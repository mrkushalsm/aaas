/* Isolated Binder transaction probe; no Android service or key material involved. */
#include <errno.h>
#include <fcntl.h>
#include <linux/android/binder.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>

static int setup(int fd) {
    struct binder_version version = {0};
    if (ioctl(fd, BINDER_VERSION, &version) || version.protocol_version != BINDER_CURRENT_PROTOCOL_VERSION)
        return -1;
    return mmap(NULL, 128 * 1024, PROT_READ, MAP_PRIVATE, fd, 0) == MAP_FAILED ? -1 : 0;
}

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    int request_sid = atoi(argv[2]);
    int server = open(argv[1], O_RDWR | O_CLOEXEC);
    if (server < 0 || setup(server)) { perror("server binder"); return 3; }
    struct flat_binder_object context = {.flags = request_sid ? FLAT_BINDER_FLAG_TXN_SECURITY_CTX : 0};
    if (ioctl(server, BINDER_SET_CONTEXT_MGR_EXT, &context)) { perror("context manager"); return 4; }
    pid_t child = fork();
    if (child < 0) { perror("fork"); return 5; }
    if (!child) {
        close(server);
        int client = open(argv[1], O_RDWR | O_CLOEXEC);
        if (client < 0 || setup(client)) { perror("client binder"); _exit(6); }
        uint32_t data = 0x12345678;
        struct binder_transaction_data transaction = {0};
        transaction.target.handle = 0;
        transaction.code = 1;
        transaction.flags = TF_ONE_WAY;
        transaction.data_size = sizeof(data);
        transaction.data.ptr.buffer = (binder_uintptr_t)(uintptr_t)&data;
        uint8_t writebuf[sizeof(uint32_t) + sizeof(transaction)];
        uint32_t command = BC_TRANSACTION;
        memcpy(writebuf, &command, sizeof(command));
        memcpy(writebuf + sizeof(command), &transaction, sizeof(transaction));
        uint8_t readbuf[512] = {0};
        struct binder_write_read rw = {
            .write_size = sizeof(writebuf), .write_buffer = (binder_uintptr_t)(uintptr_t)&writebuf,
            .read_size = sizeof(readbuf), .read_buffer = (binder_uintptr_t)(uintptr_t)readbuf,
        };
        if (ioctl(client, BINDER_WRITE_READ, &rw)) { perror("transaction ioctl"); _exit(7); }
        printf("request_sid=%d write_consumed=%llu read_consumed=%llu", request_sid,
               (unsigned long long)rw.write_consumed, (unsigned long long)rw.read_consumed);
        for (size_t off = 0; off + sizeof(uint32_t) <= rw.read_consumed; ) {
            uint32_t command;
            memcpy(&command, readbuf + off, sizeof(command));
            printf(" command=0x%x", command);
            off += sizeof(command);
            if (command == BR_ERROR && off + sizeof(int32_t) <= rw.read_consumed) {
                int32_t error;
                memcpy(&error, readbuf + off, sizeof(error));
                printf(" error=%d", error);
                off += sizeof(error);
            } else if (command != BR_NOOP && command != BR_TRANSACTION_COMPLETE &&
                       command != BR_FAILED_REPLY && command != BR_DEAD_REPLY &&
                       command != BR_SPAWN_LOOPER && command != BR_OK) break;
        }
        putchar('\n');
        fflush(stdout);
        close(client);
        _exit(0);
    }
    int status = 0;
    waitpid(child, &status, 0);
    close(server);
    return WIFEXITED(status) ? WEXITSTATUS(status) : 8;
}
