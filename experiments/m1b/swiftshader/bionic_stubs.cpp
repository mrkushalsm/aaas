#include <cstdint>
#include <cstring>
#include <cerrno>
#include <cstdlib>
#include <cstdio>
#include <cstdarg>
#include <wchar.h>
#include <wctype.h>

extern "C" {
    // Static glibc libstdc++ reads this in shared_ptr's refcount fast path.
    // Bionic does not update glibc's flag when it starts renderer threads.
    // Keep atomic refcount operations enabled from process startup.
    char __libc_single_threaded = 0;

    int *__errno_location() {
        return (&errno);
    }
    int __strcoll_l(const char *s1, const char *s2, void *) {
        return strcmp(s1, s2);
    }
    size_t __strftime_l(char *, size_t, const char *, const void *, void *) {
        return 0;
    }
    size_t __mbsrtowcs_chk(wchar_t *dst, const char **src, size_t len, mbstate_t *ps, size_t) {
        return mbsrtowcs(dst, src, len, ps);
    }
    char *__nl_langinfo_l(int item, void *) {
        static char dot[] = ".";
        static char comma[] = ",";
        static char empty[] = "";
        if (item == 0x10000) return dot;
        if (item == 0x10001) return comma;
        return empty;
    }
    void *__uselocale(void *l) {
        return l;
    }
    size_t __wcsftime_l(wchar_t *, size_t, const wchar_t *, const void *, void *) {
        return 0;
    }
    void *__duplocale(void *l) {
        static int dummy = 1;
        return l ? l : &dummy;
    }
    wchar_t *__wmemset_chk(wchar_t *s, wchar_t c, size_t n, size_t) {
        return wmemset(s, c, n);
    }
    size_t __wcsxfrm_l(wchar_t *dest, const wchar_t *src, size_t n, void *) {
        return wcsxfrm(dest, src, n);
    }
    char *bind_textdomain_codeset(const char *, const char *) {
        return nullptr;
    }
    void __freelocale(void *) {}
    size_t __strxfrm_l(char *dest, const char *src, size_t n, void *) {
        return strxfrm(dest, src, n);
    }
    char *gettext(const char *msgid) {
        return const_cast<char*>(msgid);
    }
    int __wcscoll_l(const wchar_t *s1, const wchar_t *s2, void *) {
        return wcscoll(s1, s2);
    }
    void *__newlocale(int, const char *, void *) {
        static int dummy = 1;
        return &dummy;
    }
    wchar_t *__wmemcpy_chk(wchar_t *dest, const wchar_t *src, size_t n, size_t) {
        return wmemcpy(dest, src, n);
    }
    wctype_t __wctype_l(const char *name, void *) {
        return wctype(name);
    }
    char *secure_getenv(const char *name) {
        return getenv(name);
    }
    char *dgettext(const char *, const char *msgid) {
        return const_cast<char*>(msgid);
    }
    wint_t __towlower_l(wint_t wc, void *) {
        return towlower(wc);
    }
    wint_t __towupper_l(wint_t wc, void *) {
        return towupper(wc);
    }
    int __fprintf_chk(FILE *stream, int, const char *format, ...) {
        va_list args;
        va_start(args, format);
        int r = vfprintf(stream, format, args);
        va_end(args);
        return r;
    }
    unsigned long __isoc23_strtoul(const char *nptr, char **endptr, int base) {
        return strtoul(nptr, endptr, base);
    }
    double __strtod_l(const char *nptr, char **endptr, void *) {
        return strtod(nptr, endptr);
    }
    float __strtof_l(const char *nptr, char **endptr, void *) {
        return strtof(nptr, endptr);
    }
    int __iswctype_l(wint_t wc, wctype_t desc, void *) {
        return iswctype(wc, desc);
    }
}

extern "C" {
    int atexit(void (*func)(void)) {
        extern int __cxa_atexit(void (*)(void*), void*, void*);
        extern void* __dso_handle;
        return __cxa_atexit((void (*)(void*))func, 0, &__dso_handle);
    }
    int _dl_find_object(void*, void*) {
        return -1;
    }
    struct mallinfo2_s {
        size_t arena; size_t ordblks; size_t smblks; size_t hblks; size_t hblkhd;
        size_t usmblks; size_t fsmblks; size_t uordblks; size_t fordblks; size_t keepcost;
    };
    struct mallinfo2_s mallinfo2() {
        struct mallinfo2_s m;
        memset(&m, 0, sizeof(m));
        return m;
    }
    long long __isoc23_strtoll(const char* nptr, char** endptr, int base) {
        return strtoll(nptr, endptr, base);
    }
    unsigned long long __isoc23_strtoull(const char* nptr, char** endptr, int base) {
        return strtoull(nptr, endptr, base);
    }
}

extern "C" {
    char *bindtextdomain(const char *, const char *) {
        return nullptr;
    }
    char *textdomain(const char *) {
        return nullptr;
    }
}

extern "C" {
    static int32_t tolower_tab[384];
    static int32_t toupper_tab[384];
    static uint16_t b_tab[384];
    static int ctype_init = 0;

    static void init_ctype() {
        if (ctype_init) return;
        for (int i = 0; i < 384; i++) {
            int ch = i - 128;
            tolower_tab[i] = (ch >= 'A' && ch <= 'Z') ? (ch + 32) : ch;
            toupper_tab[i] = (ch >= 'a' && ch <= 'z') ? (ch - 32) : ch;
            uint16_t mask = 0;
            if (ch >= '0' && ch <= '9') mask |= 0x0800; // _ISdigit
            if ((ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z')) mask |= 0x0400; // _ISalpha
            if (ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r') mask |= 0x2000; // _ISspace
            b_tab[i] = mask;
        }
        ctype_init = 1;
    }

    const int32_t **__ctype_tolower_loc(void) {
        init_ctype();
        static const int32_t *p = &tolower_tab[128];
        return &p;
    }

    const int32_t **__ctype_toupper_loc(void) {
        init_ctype();
        static const int32_t *p = &toupper_tab[128];
        return &p;
    }

    const uint16_t **__ctype_b_loc(void) {
        init_ctype();
        static const uint16_t *p = &b_tab[128];
        return &p;
    }
}

extern "C" {
    int bcmp(const void *s1, const void *s2, size_t n) {
        return memcmp(s1, s2, n);
    }
}
