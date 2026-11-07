/* Session-only compatibility wrapper around AOSP's preferred HIDL factory. */
typedef int int32_t;
extern "C" void* dlsym(void* handle, const char* symbol);
struct DlInfo {
    const char* file;
    void* base;
    const char* symbol;
    void* symbol_address;
};
extern "C" int dladdr(const void* address, DlInfo* info);
extern "C" int getpagesize();
extern "C" int mprotect(void* address, unsigned long length, int protection);
extern "C" void* mmap(void* address, unsigned long length, int protection,
                       int flags, int fd, long offset);
extern "C" int getuid();
extern "C" int getpid();
extern "C" int __android_log_print(int priority, const char* tag,
                                   const char* format, ...);
extern "C" void* memset(void* destination, int value, unsigned long size);
extern "C" void* aaasIpcThreadStateSelf() __asm__(
        "_ZN7android14IPCThreadState4selfEv");
extern "C" int aaasIpcThreadStateGetCallingPid(void* self) __asm__(
        "_ZNK7android14IPCThreadState13getCallingPidEv");
extern "C" int aaasIpcThreadStateGetCallingUid(void* self) __asm__(
        "_ZNK7android14IPCThreadState13getCallingUidEv");

extern "C" void* aaasServerLoadHwModule(void* statusStorage, void* self,
                                         const void* name,
                                         int32_t* result) __asm__(
        "_ZN7android25AudioFlingerServerAdapter12loadHwModuleERKNSt3__112basic_stringIcNS1_11char_traitsIcEENS1_9allocatorIcEEEEPi");
extern "C" void* aaasServerLoadHwModule(void* statusStorage, void* self,
                                         const void* name, int32_t* result) {
    constexpr char symbol[] =
            "_ZN7android25AudioFlingerServerAdapter12loadHwModuleERKNSt3__112basic_stringIcNS1_11char_traitsIcEENS1_9allocatorIcEEEEPi";
    using Original = void (*)(void*, void*, const void*, int32_t*);
    auto original = reinterpret_cast<Original>(dlsym(
            reinterpret_cast<void*>(-1), symbol));
    if (!original) {
        __android_log_print(6, "AaasHALFactoryProbe",
                            "server loadHwModule original missing");
        return statusStorage;
    }
    original(statusStorage, self, name, result);
    const auto* status = static_cast<const int32_t*>(statusStorage);
    void* ipc = aaasIpcThreadStateSelf();
    __android_log_print(4, "AaasHALFactoryProbe",
                        "server loadHwModule result=%d status0=%d status1=%d pid=%d uid=%d",
                        result ? *result : -1, status[0], status[1],
                        aaasIpcThreadStateGetCallingPid(ipc),
                        aaasIpcThreadStateGetCallingUid(ipc));
    return statusStorage;
}

extern "C" int aaasServerOnTransact(void* self, unsigned int code,
                                     const void* data, void* reply,
                                     unsigned int flags) __asm__(
        "_ZN7android25AudioFlingerServerAdapter10onTransactEjRKNS_6ParcelEPS1_j");
extern "C" int aaasServerOnTransact(void* self, unsigned int code,
                                     const void* data, void* reply,
                                     unsigned int flags) {
    constexpr char symbol[] =
            "_ZN7android25AudioFlingerServerAdapter10onTransactEjRKNS_6ParcelEPS1_j";
    using Original = int (*)(void*, unsigned int, const void*, void*, unsigned int);
    auto original = reinterpret_cast<Original>(dlsym(
            reinterpret_cast<void*>(-1), symbol));
    if (!original) {
        __android_log_print(6, "AaasHALFactoryProbe",
                            "server onTransact original missing code=%u", code);
        return -1;
    }
    const int result = original(self, code, data, reply, flags);
    __android_log_print(4, "AaasHALFactoryProbe",
                        "server onTransact code=%u result=%d flags=%u",
                        code, result, flags);
    return result;
}

void patchAudioFlingerServerAdapter() {
    constexpr char vtableSymbol[] = "_ZTVN7android25AudioFlingerServerAdapterE";
    constexpr char methodSymbol[] =
            "_ZN7android25AudioFlingerServerAdapter12loadHwModuleERKNSt3__112basic_stringIcNS1_11char_traitsIcEENS1_9allocatorIcEEEEPi";
    constexpr char transactSymbol[] =
            "_ZN7android25AudioFlingerServerAdapter10onTransactEjRKNS_6ParcelEPS1_j";
    auto** vtable = static_cast<void**>(dlsym(
            reinterpret_cast<void*>(-1), vtableSymbol));
    void* original = dlsym(reinterpret_cast<void*>(-1), methodSymbol);
    void* originalTransact = dlsym(reinterpret_cast<void*>(-1), transactSymbol);
    if (!vtable || (!original && !originalTransact)) {
        __android_log_print(5, "AaasHALFactoryProbe",
                            "server vtable patch unavailable vtable=%p method=%p",
                            vtable, original);
        return;
    }
    constexpr unsigned int entryCount = 118;  // 944-byte vtable in this image.
    unsigned int patched = 0;
    unsigned int patchedTransact = 0;
    const int pageSize = getpagesize();
    const auto begin = reinterpret_cast<unsigned long>(vtable);
    const auto end = begin + entryCount * sizeof(void*);
    const auto pageBegin = begin & ~static_cast<unsigned long>(pageSize - 1);
    const auto pageEnd = (end + static_cast<unsigned long>(pageSize - 1))
            & ~static_cast<unsigned long>(pageSize - 1);
    if (mprotect(reinterpret_cast<void*>(pageBegin), pageEnd - pageBegin, 3)) {
        __android_log_print(5, "AaasHALFactoryProbe",
                            "server vtable mprotect failed");
        return;
    }
    for (unsigned int i = 0; i < entryCount; ++i) {
        if (original && vtable[i] == original) {
            vtable[i] = reinterpret_cast<void*>(aaasServerLoadHwModule);
            ++patched;
        }
        if (originalTransact && vtable[i] == originalTransact) {
            vtable[i] = reinterpret_cast<void*>(aaasServerOnTransact);
            ++patchedTransact;
        }
    }
    (void)mprotect(reinterpret_cast<void*>(pageBegin), pageEnd - pageBegin, 1);
    __android_log_print(4, "AaasHALFactoryProbe",
                        "server vtable patched load=%u transact=%u vtable=%p original=%p originalTransact=%p",
                        patched, patchedTransact, vtable, original,
                        originalTransact);
}

namespace android {

class RefBase {
public:
    void incStrong(const void* id) const __asm__(
            "_ZNK7android7RefBase9incStrongEPKv");
    void decStrong(const void* id) const __asm__(
            "_ZNK7android7RefBase9decStrongEPKv");
};

template <typename T>
class sp {
public:
    explicit sp(T* value) : mValue(value) {
        if (mValue) reinterpret_cast<RefBase*>(mValue)->incStrong(this);
        __android_log_print(4, "AaasHALFactoryProbe",
                            "sp_construct this=%p value=%p", this, mValue);
    }
    sp(const sp&) = delete;
    sp& operator=(const sp&) = delete;
    ~sp() {
        __android_log_print(4, "AaasHALFactoryProbe",
                            "sp_destroy this=%p value=%p", this, mValue);
        if (mValue) reinterpret_cast<RefBase*>(mValue)->decStrong(this);
    }

private:
    T* mValue;
};

class DevicesFactoryHalInterface : public RefBase {};
class EffectsFactoryHalInterface : public RefBase {};

void* gLastInspectedAudioFlinger = nullptr;
using AudioFlingerLoadModule = int (*)(void*, const char*);
AudioFlingerLoadModule gOriginalAudioFlingerLoadModule = nullptr;
void* gAudioFlingerImageBase = nullptr;
bool gPermissionProbeInstalled = false;

void* aaasEnforceAudioPermission(void* result, void* self, int permission) {
    using Enforce = void* (*)(void*, void*, int);
    auto enforce = reinterpret_cast<Enforce>(
            static_cast<char*>(gAudioFlingerImageBase) + 0xead00);
    void* returned = enforce(result, self, permission);
    const auto* words = static_cast<const unsigned int*>(result);
    __android_log_print(4, "AaasHALFactoryProbe",
                        "enforceCallingPermission permission=%d words=%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x",
                        permission, words[0], words[1], words[2], words[3],
                        words[4], words[5], words[6], words[7]);
    return returned;
}

void installPermissionProbe() {
    if (gPermissionProbeInstalled || !gAudioFlingerImageBase) return;
    gPermissionProbeInstalled = true;
    constexpr unsigned long callOffset = 0xba21c;
    auto* callsite = static_cast<unsigned char*>(gAudioFlingerImageBase)
            + callOffset;
    const unsigned char expected[] = {0xe8, 0xdf, 0x0a, 0x03, 0x00};
    for (unsigned int i = 0; i < sizeof(expected); ++i) {
        if (callsite[i] != expected[i]) {
            __android_log_print(5, "AaasHALFactoryProbe",
                                "permission probe callsite mismatch byte=%u got=%02x",
                                i, callsite[i]);
            return;
        }
    }
    constexpr int protReadWrite = 3;
    constexpr int protReadExec = 5;
    constexpr int mapPrivateAnonymous = 0x22;
    const int pageSize = getpagesize();
    void* hint = static_cast<char*>(gAudioFlingerImageBase) + 0x10000000;
    auto* stub = static_cast<unsigned char*>(mmap(
            hint, static_cast<unsigned long>(pageSize), protReadWrite,
            mapPrivateAnonymous, -1, 0));
    if (stub == reinterpret_cast<void*>(-1)) {
        __android_log_print(5, "AaasHALFactoryProbe",
                            "permission probe near mapping failed");
        return;
    }
    const auto distance = reinterpret_cast<long>(stub)
            - reinterpret_cast<long>(callsite + sizeof(expected));
    if (distance < -2147483647L || distance > 2147483647L) {
        __android_log_print(5, "AaasHALFactoryProbe",
                            "permission probe stub outside rel32 range");
        return;
    }
    stub[0] = 0x48;  // movabs rax, aaasEnforceAudioPermission
    stub[1] = 0xb8;
    *reinterpret_cast<unsigned long long*>(stub + 2) =
            reinterpret_cast<unsigned long long>(aaasEnforceAudioPermission);
    stub[10] = 0xff;  // jmp rax, preserving the caller's hidden result pointer
    stub[11] = 0xe0;
    if (mprotect(stub, static_cast<unsigned long>(pageSize), protReadExec)) {
        __android_log_print(5, "AaasHALFactoryProbe",
                            "permission probe stub executable protection failed");
        return;
    }
    const auto callPage = reinterpret_cast<unsigned long>(callsite)
            & ~static_cast<unsigned long>(pageSize - 1);
    if (mprotect(reinterpret_cast<void*>(callPage),
                 static_cast<unsigned long>(pageSize), protReadWrite)) {
        __android_log_print(5, "AaasHALFactoryProbe",
                            "permission probe text write protection failed");
        return;
    }
    const int relative = static_cast<int>(distance);
    *reinterpret_cast<int*>(callsite + 1) = relative;
    __builtin___clear_cache(reinterpret_cast<char*>(callsite),
                            reinterpret_cast<char*>(callsite + sizeof(expected)));
    (void)mprotect(reinterpret_cast<void*>(callPage),
                   static_cast<unsigned long>(pageSize), protReadExec);
    __android_log_print(4, "AaasHALFactoryProbe",
                        "permission probe installed call=%p stub=%p",
                        callsite, stub);
}

int aaasAudioFlingerLoadModule(void* self, const char* name) {
    void* ipc = aaasIpcThreadStateSelf();
    const int callingPid = aaasIpcThreadStateGetCallingPid(ipc);
    const int callingUid = aaasIpcThreadStateGetCallingUid(ipc);
    __android_log_print(4, "AaasHALFactoryProbe",
                        "AudioFlinger::loadHwModule begin name=%s pid=%d uid=%d binderPid=%d binderUid=%d",
                        name ? name : "(null)", getpid(), getuid(),
                        callingPid, callingUid);
    installPermissionProbe();
    const int result = gOriginalAudioFlingerLoadModule
            ? gOriginalAudioFlingerLoadModule(self, name) : 0;
    __android_log_print(4, "AaasHALFactoryProbe",
                        "AudioFlinger::loadHwModule end result=%d name=%s",
                        result, name ? name : "(null)");
    return result;
}

extern "C" void* aaasGetAudioFlinger(void* result) __asm__(
        "_ZN7android11AudioSystem17get_audio_flingerEv");
extern "C" void* aaasGetAudioFlinger(void* result) {
    constexpr char symbol[] = "_ZN7android11AudioSystem17get_audio_flingerEv";
    using Original = void* (*)(void*);
    auto original = reinterpret_cast<Original>(dlsym(
            reinterpret_cast<void*>(-1), symbol));
    if (!original) {
        __android_log_print(6, "AaasHALFactoryProbe",
                            "AudioSystem get_audio_flinger missing");
        return result;
    }
    void* returned = original(result);
    patchAudioFlingerServerAdapter();
    DlInfo callerInfo{};
    void* caller = __builtin_return_address(0);
    (void)dladdr(caller, &callerInfo);
    __android_log_print(4, "AaasHALFactoryProbe",
                        "AudioSystem get_audio_flinger result=%p caller=%p base=%p caller_symbol=%s",
                        result ? *reinterpret_cast<void**>(result) : nullptr,
                        caller, callerInfo.base,
                        callerInfo.symbol ? callerInfo.symbol : "(unknown)");
    void* object = result ? *reinterpret_cast<void**>(result) : nullptr;
    if (object && object != gLastInspectedAudioFlinger) {
        gLastInspectedAudioFlinger = object;
        auto** vtable = *reinterpret_cast<void***>(object);
        __android_log_print(4, "AaasHALFactoryProbe",
                            "AudioFlinger interface object=%p vtable=%p",
                            object, vtable);
        for (unsigned int slot = 40; slot < 58; ++slot) {
            DlInfo slotInfo{};
            (void)dladdr(vtable[slot], &slotInfo);
            const long slotOffset = slotInfo.base
                    ? reinterpret_cast<char*>(vtable[slot])
                            - reinterpret_cast<char*>(slotInfo.base)
                    : -1;
            __android_log_print(4, "AaasHALFactoryProbe",
                                "AudioFlinger vtable slot=%u fn=%p offset=%ld dso=%s symbol=%s",
                                slot, vtable[slot],
                                slotOffset,
                                slotInfo.file ? slotInfo.file : "(unknown)",
                                slotInfo.symbol ? slotInfo.symbol : "(unknown)");
        }
        // The Android 16 audioserver caller disassembly for
        // AudioPolicyClient::loadHwModule calls vtable byte offset 0x168.
        constexpr unsigned int loadModuleSlot = 0x168 / sizeof(void*);
        gOriginalAudioFlingerLoadModule =
                reinterpret_cast<AudioFlingerLoadModule>(vtable[loadModuleSlot]);
        DlInfo audioFlingerInfo{};
        (void)dladdr(reinterpret_cast<const void*>(
                             gOriginalAudioFlingerLoadModule),
                     &audioFlingerInfo);
        gAudioFlingerImageBase = audioFlingerInfo.base;
        const int pageSize = getpagesize();
        const auto slotAddress = reinterpret_cast<unsigned long>(
                &vtable[loadModuleSlot]);
        void* page = reinterpret_cast<void*>(slotAddress &
                ~static_cast<unsigned long>(pageSize - 1));
        if (gOriginalAudioFlingerLoadModule
                && mprotect(page, static_cast<unsigned long>(pageSize), 3) == 0) {
            vtable[loadModuleSlot] = reinterpret_cast<void*>(
                    aaasAudioFlingerLoadModule);
            (void)mprotect(page, static_cast<unsigned long>(pageSize), 1);
            __android_log_print(4, "AaasHALFactoryProbe",
                                "patched AudioFlinger loadHwModule slot=%u object=%p",
                                loadModuleSlot, object);
        } else {
            __android_log_print(5, "AaasHALFactoryProbe",
                                "could not patch AudioFlinger loadHwModule slot=%u",
                                loadModuleSlot);
        }
    }
    return returned;
}

namespace {
using PreferredCreate = void* (*)(bool);

void* preferredFactory(bool isDevice) {
    auto create = reinterpret_cast<PreferredCreate>(dlsym(
            reinterpret_cast<void*>(-1),
            "_ZN7android6detail19createPreferredImplEb"));
    return create ? create(isDevice) : nullptr;
}

template <typename Interface>
sp<Interface> createPreferred(bool isDevice, const char* name,
                              const void* caller) {
    auto* raw = static_cast<Interface*>(preferredFactory(isDevice));
    DlInfo callerInfo{};
    (void)dladdr(caller, &callerInfo);
    __android_log_print(4, "AaasHALFactoryProbe",
                        "factory=%s preferred=%p caller=%p dso=%s symbol=%s",
                        name, raw, caller,
                        callerInfo.file ? callerInfo.file : "(unknown)",
                        callerInfo.symbol ? callerInfo.symbol : "(unknown)");
    return sp<Interface>(raw);
}
}  // namespace

sp<DevicesFactoryHalInterface> aaasDevicesFactoryCreate() __asm__(
        "_ZN7android26DevicesFactoryHalInterface6createEv");
sp<DevicesFactoryHalInterface> aaasDevicesFactoryCreate() {
    return createPreferred<DevicesFactoryHalInterface>(true,
            "DevicesFactoryHalInterface", __builtin_return_address(0));
}

sp<EffectsFactoryHalInterface> aaasEffectsFactoryCreate() __asm__(
        "_ZN7android26EffectsFactoryHalInterface6createEv");
sp<EffectsFactoryHalInterface> aaasEffectsFactoryCreate() {
    return createPreferred<EffectsFactoryHalInterface>(false,
            "EffectsFactoryHalInterface", __builtin_return_address(0));
}

}  // namespace android
