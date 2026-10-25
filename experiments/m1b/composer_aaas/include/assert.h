#pragma once
#include <stdlib.h>

#ifndef assert
#define assert(expr) ((void)0)
#endif

#ifdef __cplusplus
extern "C" {
#endif
void __assert(const char* file, int line, const char* msg);
void __assert2(const char* file, int line, const char* func, const char* expr);
#ifdef __cplusplus
}
#endif
