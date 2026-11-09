#include "resize_generation.h"

#include <assert.h>
#include <stdio.h>
#include <sys/stat.h>

static void write_value(const char *path, const char *value) {
    FILE *file = fopen(path, "w");
    assert(file != NULL);
    assert(fputs(value, file) >= 0);
    assert(fclose(file) == 0);
}

int main(void) {
    char path[] = "/tmp/aaas-resize-generation-XXXXXX";
    int fd = mkstemp(path);
    assert(fd >= 0);
    close(fd);

    assert(aaas_read_resize_generation_seed(NULL) == 0);
    assert(aaas_read_resize_generation_seed(path) == 0);
    write_value(path, "2 493 783\n");
    assert(aaas_read_resize_generation_seed(path) == 2);
    write_value(path, "4294967295 720 1280\n");
    assert(aaas_read_resize_generation_seed(path) == 0);
    write_value(path, "not-a-generation\n");
    assert(aaas_read_resize_generation_seed(path) == 0);

    char link_path[128];
    snprintf(link_path, sizeof(link_path), "%s-link", path);
    assert(symlink(path, link_path) == 0);
    assert(aaas_read_resize_generation_seed(link_path) == 0);
    assert(unlink(link_path) == 0);
    assert(unlink(path) == 0);
    puts("resize generation seed tests passed");
    return 0;
}
