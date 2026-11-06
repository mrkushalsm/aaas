package org.aaas.audioprobe;

import android.app.Activity;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.os.Bundle;
import android.util.Log;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private static final String TAG = "AaasAudioProbe";

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        final TextView view = new TextView(this);
        view.setText("AaaS audio probe: playing a quiet 440 Hz stereo tone");
        setContentView(view);
        new Thread(new Runnable() {
            @Override public void run() {
                AudioTrack track = null;
                try {
                    int rate = 48000;
                    int frames = rate;
                    short[] pcm = new short[frames * 2];
                    for (int i = 0; i < frames; i++) {
                        short sample = (short)(3000.0 * Math.sin(2.0 * Math.PI * 440.0 * i / rate));
                        pcm[i * 2] = sample;
                        pcm[i * 2 + 1] = sample;
                    }
                    int bufferBytes = Math.max(pcm.length * 2,
                            AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_STEREO,
                                    AudioFormat.ENCODING_PCM_16BIT));
                    track = new AudioTrack(AudioManager.STREAM_MUSIC, rate,
                            AudioFormat.CHANNEL_OUT_STEREO, AudioFormat.ENCODING_PCM_16BIT,
                            bufferBytes, AudioTrack.MODE_STREAM);
                    track.play();
                    int written = 0;
                    while (written < pcm.length) {
                        int count = track.write(pcm, written, pcm.length - written);
                        if (count <= 0) throw new IllegalStateException("AudioTrack.write=" + count);
                        written += count;
                    }
                    Log.i(TAG, "PLAYBACK_OK rate=" + rate + " channels=2 frames=" + (written / 2));
                    Thread.sleep(1100);
                } catch (Throwable error) {
                    Log.e(TAG, "PLAYBACK_FAILED " + error.getClass().getSimpleName(), error);
                } finally {
                    if (track != null) {
                        try { track.stop(); } catch (Throwable ignored) {}
                        track.release();
                    }
                }
            }
        }, "aaas-audio-probe").start();
    }
}
