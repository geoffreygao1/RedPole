"""Shared audio file I/O helpers used by both the loop engine and the
soundscape/synth engine. Moved out of audio_engine.py so the synth engine
can load samples without importing the whole loop-mode engine."""

import numpy as np
import soundfile as sf

MAX_LOOP_SECONDS = 600.0
LOAD_CHUNK_FRAMES = 262144


def resample_linear(data, source_rate, target_rate):
    if source_rate == target_rate or len(data) == 0:
        return data.astype(np.float32)
    target_len = max(1, int(round(len(data) * target_rate / source_rate)))
    source_x = np.linspace(0.0, 1.0, len(data), endpoint=False)
    target_x = np.linspace(0.0, 1.0, target_len, endpoint=False)
    return np.interp(target_x, source_x, data).astype(np.float32)


def read_mono_audio(path, max_seconds=None):
    if max_seconds is None:
        max_seconds = MAX_LOOP_SECONDS
    chunks = []
    with sf.SoundFile(path) as file:
        file_rate = file.samplerate
        frames_to_read = len(file)
        if max_seconds is not None:
            frames_to_read = min(frames_to_read, max(1, int(max_seconds * file_rate)))

        remaining = frames_to_read
        while remaining > 0:
            block = file.read(
                min(LOAD_CHUNK_FRAMES, remaining),
                dtype="float32",
                always_2d=True,
            )
            if len(block) == 0:
                break
            chunks.append(block.mean(axis=1).astype(np.float32))
            remaining -= len(block)

    if not chunks:
        return np.zeros(0, dtype=np.float32), file_rate
    return np.concatenate(chunks).astype(np.float32), file_rate
