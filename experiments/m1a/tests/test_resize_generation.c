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

    aaas_resize_resume_state state = aaas_read_resize_resume_state(NULL);
    assert(state.generation == 0 && state.width == 0 && state.height == 0);
    state = aaas_read_resize_resume_state(path);
    assert(state.generation == 0 && state.width == 0 && state.height == 0);
    write_value(path, "2 493 783\n");
    state = aaas_read_resize_resume_state(path);
    assert(state.generation == 2 && state.width == 493 && state.height == 783);
    write_value(path, "4294967295 720 1280\n");
    assert(aaas_read_resize_resume_state(path).generation == 0);
    write_value(path, "2 4294967296 1280\n");
    assert(aaas_read_resize_resume_state(path).generation == 0);
    write_value(path, "not-a-generation\n");
    assert(aaas_read_resize_resume_state(path).generation == 0);

    char link_path[128];
    snprintf(link_path, sizeof(link_path), "%s-link", path);
    assert(symlink(path, link_path) == 0);
    assert(aaas_read_resize_resume_state(link_path).generation == 0);
    assert(unlink(link_path) == 0);
    assert(unlink(path) == 0);
    puts("resize generation seed tests passed");
    return 0;
}
