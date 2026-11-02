.class public Lorg/aaas/latencyprobe/ProbeActivity;
.super Landroid/app/Activity;

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method

.method protected onCreate(Landroid/os/Bundle;)V
    .locals 3
    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V
    invoke-virtual {p0}, Landroid/app/Activity;->getWindow()Landroid/view/Window;
    move-result-object v0
    const/16 v1, 0x400
    invoke-virtual {v0, v1, v1}, Landroid/view/Window;->setFlags(II)V
    new-instance v0, Lorg/aaas/latencyprobe/MarkerView;
    invoke-direct {v0, p0}, Lorg/aaas/latencyprobe/MarkerView;-><init>(Landroid/content/Context;)V
    invoke-virtual {p0, v0}, Landroid/app/Activity;->setContentView(Landroid/view/View;)V
    return-void
.end method
