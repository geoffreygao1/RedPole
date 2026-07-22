"""Shared per-voice lifecycle helper: every soundscape engine keeps a
dict[layer_id -> state], created on first sight, garbage-collected here
when a layer id disappears -- the same create/GC idiom already used by
MicrocosmProcessor and SynthVoiceBank."""


def sync_voices(voices, active_ids):
    active = set(active_ids)
    for vid in [v for v in voices if v not in active]:
        del voices[vid]
