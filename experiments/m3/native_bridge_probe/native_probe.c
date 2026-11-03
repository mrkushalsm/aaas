#include "jni.h"
#include <arm_neon.h>

#ifndef NULL
#define NULL ((void *)0)
#endif

static jint invalid_argument_result(jint value) {
  return value < 0 ? -22 : 0;
}

// The return value is compared byte-for-byte by Java. A result is returned
// only after ARM64 computations and the Java callback have all been checked.
JNIEXPORT jstring JNICALL
Java_org_aaas_latencyprobe_NativeProbe_runAll(
    JNIEnv *env, jclass klass, jint left, jint right, jlong wide_left,
    jlong wide_right, jdouble fp_left, jdouble fp_right, jstring input,
    jintArray values, jobject callback) {
  (void)klass;
  jint mask = 0;
  jint int_result = left * 7 + right * 11 - 5;
  if (left == 7 && right == 3 && int_result == 77) mask |= 1 << 0;

  jlong wide_result = wide_left * 31 + wide_right;
  if (wide_left == INT64_C(1234567890123) && wide_right == 9 &&
      wide_result == INT64_C(38271604593822)) mask |= 1 << 1;

  jdouble fp_result = fp_left * 0.5 + fp_right * 1.5;
  if (fp_left == 2.0 && fp_right == 4.0 && fp_result == 7.0) mask |= 1 << 2;

  const char *utf = (*env)->GetStringUTFChars(env, input, NULL);
  if (utf != NULL) {
    if (utf[0] == 'A' && utf[1] == 'a' && utf[2] == 'a' && utf[3] == 'S' &&
        utf[4] == ' ' && utf[5] == 'M' && utf[6] == '3' && utf[7] == '\0') {
      mask |= 1 << 3;
    }
    (*env)->ReleaseStringUTFChars(env, input, utf);
  }

  jsize count = (*env)->GetArrayLength(env, values);
  jint sum = 0;
  jint *elements = (*env)->GetIntArrayElements(env, values, NULL);
  if (elements != NULL) {
    for (jsize i = 0; i < count; ++i) sum += elements[i];
    (*env)->ReleaseIntArrayElements(env, values, elements, JNI_ABORT);
  }
  if (count == 4 && sum == 10) mask |= 1 << 4;

  jclass callback_class = (*env)->GetObjectClass(env, callback);
  jmethodID method = callback_class == NULL ? NULL :
      (*env)->GetMethodID(env, callback_class, "nativeCallbackValue", "(I)I");
  jint callback_result = method == NULL ? 0 :
      (*env)->CallIntMethod(env, callback, method, 14);
  if (method != NULL && !(*env)->ExceptionCheck(env) && callback_result == 42) {
    mask |= 1 << 5;
  }

  if (invalid_argument_result(-1) == -22) mask |= 1 << 6;
  const jint lhs[4] = {1, 2, 3, 4};
  const jint rhs[4] = {4, 3, 2, 1};
  jint lanes[4] = {0, 0, 0, 0};
  int32x4_t vector_sum = vaddq_s32(vld1q_s32(lhs), vld1q_s32(rhs));
  vst1q_s32(lanes, vector_sum);
  if (lanes[0] == 5 && lanes[1] == 5 && lanes[2] == 5 && lanes[3] == 5) {
    mask |= 1 << 7;
  }
  if (mask == 0xff) {
    return (*env)->NewStringUTF(env,
        "M3 ARM64 Native Bridge PASS mask=255 int=77 array=10 callback=42 "
        "error=-22 long=38271604593822 double=7.0 neon=5x4 echo=AaaS M3");
  }
  return (*env)->NewStringUTF(env, "M3 ARM64 Native Bridge FAIL mask mismatch");
}
