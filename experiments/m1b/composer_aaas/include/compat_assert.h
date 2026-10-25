#pragma once
#include <syslog.h>
#include <stdlib.h>
#define __ANDROID_API__ 35
#ifdef __cplusplus
extern "C" {
#endif
void __assert2(const char* file, int line, const char* func, const char* expr);
#ifdef __cplusplus
}
#endif
