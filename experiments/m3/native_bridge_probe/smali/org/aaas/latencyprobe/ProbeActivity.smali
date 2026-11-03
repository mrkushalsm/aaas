.class public Lorg/aaas/latencyprobe/ProbeActivity;
.super Landroid/app/Activity;

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method

.method public nativeCallbackValue(I)I
    .locals 1
    mul-int/lit8 v0, p1, 0x3
    return v0
.end method

.method protected onCreate(Landroid/os/Bundle;)V
    .locals 13
    invoke-super/range {p0 .. p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V
    const-string v0, "m3probe"
    invoke-static {v0}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V

    const/4 v0, 0x7
    const/4 v1, 0x3
    const-wide v2, 0x0000011f71fb04cbL
    const-wide v4, 0x0000000000000009L
    const-wide v6, 0x4000000000000000L
    const-wide v8, 0x4010000000000000L
    const-string v10, "AaaS M3"
    const/4 v11, 0x4
    new-array v11, v11, [I
    const/4 v12, 0x0
    const/4 v0, 0x1
    aput v0, v11, v12
    const/4 v12, 0x1
    const/4 v0, 0x2
    aput v0, v11, v12
    const/4 v12, 0x2
    const/4 v0, 0x3
    aput v0, v11, v12
    const/4 v12, 0x3
    const/4 v0, 0x4
    aput v0, v11, v12
    const/4 v0, 0x7
    const/4 v1, 0x3
    move-object/from16 v12, p0
    invoke-static/range {v0 .. v12}, Lorg/aaas/latencyprobe/NativeProbe;->runAll(IIJJDDLjava/lang/String;[ILorg/aaas/latencyprobe/ProbeActivity;)Ljava/lang/String;
    move-result-object v0

    const-string v1, "M3 ARM64 Native Bridge PASS mask=255 int=77 array=10 callback=42 error=-22 long=38271604593822 double=7.0 neon=5x4 echo=AaaS M3"
    invoke-virtual {v1, v0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v2
    if-eqz v2, :failed
    const-string v2, "AaaSM3"
    invoke-static {v2, v0}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    goto :show

:failed
    const-string v0, "M3 ARM64 Native Bridge FAIL; inspect NativeProbe diagnostics"
    const-string v2, "AaaSM3"
    invoke-static {v2, v0}, Landroid/util/Log;->e(Ljava/lang/String;Ljava/lang/String;)I

:show
    new-instance v3, Landroid/widget/TextView;
    invoke-direct {v3, p0}, Landroid/widget/TextView;-><init>(Landroid/content/Context;)V
    invoke-virtual {v3, v0}, Landroid/widget/TextView;->setText(Ljava/lang/CharSequence;)V
    invoke-virtual {p0, v3}, Landroid/app/Activity;->setContentView(Landroid/view/View;)V
    return-void
.end method
