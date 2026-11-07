/*
 * Route Android 16 legacy-audio factory creation through the preferred HIDL
 * implementation. Ranchu's default factory path is incompatible with this
 * rootless runtime. This compatibility interposer contains no diagnostics or
 * AudioFlinger permission-policy patching.
 */
extern "C" void* dlsym(void* handle, const char* symbol);

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
    explicit sp(T* value) : value_(value) {
        if (value_) reinterpret_cast<RefBase*>(value_)->incStrong(this);
    }
    sp(const sp&) = delete;
    sp& operator=(const sp&) = delete;
    ~sp() {
        if (value_) reinterpret_cast<RefBase*>(value_)->decStrong(this);
    }

private:
    T* value_;
};

class DevicesFactoryHalInterface : public RefBase {};
class EffectsFactoryHalInterface : public RefBase {};

using PreferredCreate = void* (*)(bool);

void* createPreferred(bool deviceFactory) {
    auto create = reinterpret_cast<PreferredCreate>(dlsym(
            reinterpret_cast<void*>(-1),
            "_ZN7android6detail19createPreferredImplEb"));
    return create ? create(deviceFactory) : nullptr;
}

template <typename Interface>
sp<Interface> makeFactory(bool deviceFactory) {
    return sp<Interface>(static_cast<Interface*>(createPreferred(deviceFactory)));
}

sp<DevicesFactoryHalInterface> aaasDevicesFactoryCreate() __asm__(
        "_ZN7android26DevicesFactoryHalInterface6createEv");
sp<DevicesFactoryHalInterface> aaasDevicesFactoryCreate() {
    return makeFactory<DevicesFactoryHalInterface>(true);
}

sp<EffectsFactoryHalInterface> aaasEffectsFactoryCreate() __asm__(
        "_ZN7android26EffectsFactoryHalInterface6createEv");
sp<EffectsFactoryHalInterface> aaasEffectsFactoryCreate() {
    return makeFactory<EffectsFactoryHalInterface>(false);
}

}  // namespace android
