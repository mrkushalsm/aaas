.class public final Lorg/aaas/latencyprobe/MarkerView;
.super Landroid/view/View;

.field private state:I
.field private paint:Landroid/graphics/Paint;

.method public constructor <init>(Landroid/content/Context;)V
    .locals 1
    invoke-direct {p0, p1}, Landroid/view/View;-><init>(Landroid/content/Context;)V
    new-instance v0, Landroid/graphics/Paint;
    invoke-direct {v0}, Landroid/graphics/Paint;-><init>()V
    iput-object v0, p0, Lorg/aaas/latencyprobe/MarkerView;->paint:Landroid/graphics/Paint;
    const/4 v0, 0x1
    invoke-virtual {p0, v0}, Lorg/aaas/latencyprobe/MarkerView;->setClickable(Z)V
    return-void
.end method

.method protected onDraw(Landroid/graphics/Canvas;)V
    .locals 13
    invoke-super {p0, p1}, Landroid/view/View;->onDraw(Landroid/graphics/Canvas;)V
    const v0, -14671840
    invoke-virtual {p1, v0}, Landroid/graphics/Canvas;->drawColor(I)V
    iget v0, p0, Lorg/aaas/latencyprobe/MarkerView;->state:I
    const/4 v1, 0x0
:marker_loop
    const/16 v2, 0x8
    if-ge v1, v2, :marker_done
    and-int/lit8 v2, v0, 0x1
    if-eqz v2, :marker_zero
    const v2, -1
    goto :marker_color
:marker_zero
    const v2, -8947849
:marker_color
    iget-object v7, p0, Lorg/aaas/latencyprobe/MarkerView;->paint:Landroid/graphics/Paint;
    invoke-virtual {v7, v2}, Landroid/graphics/Paint;->setColor(I)V
    int-to-float v3, v1
    const/high16 v4, 0x42200000    # 40.0f
    mul-float/2addr v3, v4
    const/high16 v4, 0x41c00000    # 24.0f
    add-float/2addr v3, v4
    const/high16 v4, 0x42a00000    # 80.0f
    const/high16 v5, 0x41c00000    # 24.0f
    add-float v5, v3, v5
    const/high16 v6, 0x43340000    # 180.0f
    move-object v12, v7
    move-object v7, p1
    move v8, v3
    move v9, v4
    move v10, v5
    move v11, v6
    invoke-virtual/range {v7 .. v12}, Landroid/graphics/Canvas;->drawRect(FFFFLandroid/graphics/Paint;)V
    shr-int/lit8 v0, v0, 0x1
    add-int/lit8 v1, v1, 0x1
    goto :marker_loop
:marker_done
    return-void
.end method

.method public onTouchEvent(Landroid/view/MotionEvent;)Z
    .locals 2
    invoke-virtual {p1}, Landroid/view/MotionEvent;->getAction()I
    move-result v0
    const/4 v1, 0x0
    if-ne v0, v1, :touch_consumed
    iget v0, p0, Lorg/aaas/latencyprobe/MarkerView;->state:I
    add-int/lit8 v0, v0, 0x1
    iput v0, p0, Lorg/aaas/latencyprobe/MarkerView;->state:I
    invoke-virtual {p0}, Lorg/aaas/latencyprobe/MarkerView;->invalidate()V
:touch_consumed
    return v1
.end method
