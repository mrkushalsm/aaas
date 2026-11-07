#define _GNU_SOURCE
#include <dlfcn.h>
#include <hardware/hardware.h>
#include <android/log.h>

typedef int (*get_module_fn)(const char *, const char *,
                             const struct hw_module_t **);

int hw_get_module_by_class(const char *id, const char *inst,
                           const struct hw_module_t **module) {
    static get_module_fn real_function;
    if (!real_function) {
        real_function = (get_module_fn)dlsym(RTLD_NEXT,
                                             "hw_get_module_by_class");
    }
    Dl_info caller = {0};
    (void)dladdr(__builtin_return_address(0), &caller);
    __android_log_print(ANDROID_LOG_INFO, "AaasHALLoader",
                        "lookup begin id=%s instance=%s caller=%s",
                        id ? id : "(null)", inst ? inst : "(null)",
                        caller.dli_fname ? caller.dli_fname : "(unknown)");
    if (!real_function) {
        __android_log_print(ANDROID_LOG_ERROR, "AaasHALLoader",
                            "dlsym hw_get_module_by_class failed: %s",
                            dlerror());
        return -1;
    }
    const int result = real_function(id, inst, module);
    __android_log_print(ANDROID_LOG_INFO, "AaasHALLoader",
                        "lookup end id=%s instance=%s result=%d module=%p",
                        id ? id : "(null)", inst ? inst : "(null)",
                        result, module ? (const void *)*module : NULL);
    if (result == 0 && module && *module) {
        __android_log_print(ANDROID_LOG_INFO, "AaasHALLoader",
                            "module id=%s name=%s author=%s api=%u hal=%u",
                            (*module)->id ? (*module)->id : "(null)",
                            (*module)->name ? (*module)->name : "(null)",
                            (*module)->author ? (*module)->author : "(null)",
                            (*module)->module_api_version,
                            (*module)->hal_api_version);
    }
    return result;
}
