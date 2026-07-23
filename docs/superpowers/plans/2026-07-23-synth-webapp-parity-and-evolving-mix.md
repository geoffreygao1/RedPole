# Synth Web-App Parity + Evolving Mix + Live Root Slider — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the desktop Synth tab's workflow in line with the GitHub-Pages web app (Send → Sources list → assign to a generator jack → cable to a modifier, single-use sources, Play/Pause), make the soundscape ebb and flow via a slow evolving-mix conductor, and turn the harmonic root into a live gliding slider.

**Architecture:** Three layers. (1) A new `VoiceConductor` and a gliding root in `SoundscapeEngine.generate_block` produce time-varying per-voice gains and real-time re-pitching. (2) `SynthAudioEngine` gets thread-safe `set_root`; `SoundscapeEngine` gets `set_patch_transform`. (3) A pure `SynthPatchModel` holds the source/voice/jack state, and the `SynthTab` widget is rewritten around it with a Send button, Sources list, click-assign, generator→modifier cabling, Play/Pause, and a root slider.

**Tech Stack:** Python 3, NumPy, Tkinter, sounddevice, pytest. Flat module layout in `audio_prototype/` (tests import modules directly; `conftest.py` puts the dir on `sys.path`).

## Global Constraints

- All work is under `audio_prototype/`. Run tests from that directory: `rtk python -m pytest <path> -v`.
- NumPy-only DSP (no scipy). Keep the audio path allocation-light but correctness first.
- Tk widget tests must skip gracefully when no display is available (reuse `_tk_root_or_skip` from `tests/test_synth_tab.py`).
- Prefix shell/git commands with `rtk`. Commit style: Conventional Commits (`feat:`, `fix:`, `test:`, `refactor:`). End commit messages with the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer.
- Determinism: seeded RNGs must produce identical output across runs for a given `(seed, id)`.

---

### Task 1: `SoundscapeEngine.set_patch_transform`

Let a placed voice's modifier be set or cleared without recreating the patch.

**Files:**
- Modify: `audio_prototype/soundscape_engine.py` (add method to `SoundscapeEngine`, after `disconnect_patch`)
- Test: `audio_prototype/tests/test_soundscape_engine.py`

**Interfaces:**
- Consumes: existing `SoundscapePatch.transform_preset` slot (already mutable).
- Produces: `SoundscapeEngine.set_patch_transform(pid: int, transform_preset: str | None) -> None`.

- [ ] **Step 1: Write the failing test**

```python
def test_set_patch_transform_updates_and_clears_without_new_patch():
    engine = SoundscapeEngine(samplerate=44100, seed=1)
    pid = engine.connect_patch(hue=0.03, sat=0.68, val=0.94, bpm=90.0,
                               source_preset="additive_2", transform_preset=None)
    engine.set_patch_transform(pid, "delay_1")
    assert engine._patches[pid].transform_preset == "delay_1"
    engine.set_patch_transform(pid, None)
    assert engine._patches[pid].transform_preset is None
    assert list(engine._patches.keys()) == [pid]  # same patch, no new id
    engine.set_patch_transform(9999, "delay_1")   # unknown pid is a no-op
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_soundscape_engine.py::test_set_patch_transform_updates_and_clears_without_new_patch -v`
Expected: FAIL with `AttributeError: 'SoundscapeEngine' object has no attribute 'set_patch_transform'`

- [ ] **Step 3: Write minimal implementation**

Add to `SoundscapeEngine`, immediately after `disconnect_patch`:

```python
    def set_patch_transform(self, pid, transform_preset):
        patch = self._patches.get(pid)
        if patch is not None:
            patch.transform_preset = transform_preset
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_soundscape_engine.py::test_set_patch_transform_updates_and_clears_without_new_patch -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_engine.py audio_prototype/tests/test_soundscape_engine.py
rtk git commit -m "feat(soundscape): set_patch_transform to retarget a voice's modifier"
```

---

### Task 2: `VoiceConductor` (evolving-mix gains)

A deterministic, slow, per-voice gain generator: fades voices in/out and rotates foreground membership. Gentle & slow (20–50 s swells).

**Files:**
- Create: `audio_prototype/soundscape_conductor.py`
- Test: `audio_prototype/tests/test_soundscape_conductor.py`

**Interfaces:**
- Consumes: `soundscape_density.assign_voice_roles`, `soundscape_density.ROLE_GAIN`.
- Produces: `VoiceConductor(samplerate: float, seed=None, min_period=20.0, max_period=50.0, swell_min=0.35, swell_depth=0.65, smooth_tau=0.6)`; method `update(active_ids: list[int], frames: int) -> dict[int, float]` returning a smoothed gain per active id. Advances internal time by `frames / samplerate` each call and GCs state for ids not present.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np

from soundscape_conductor import VoiceConductor
from soundscape_density import ROLE_GAIN


def test_gains_are_bounded_and_present_for_active_ids():
    c = VoiceConductor(samplerate=44100, seed=1)
    gains = c.update([1, 2, 3], 1024)
    assert set(gains) == {1, 2, 3}
    hi = max(ROLE_GAIN.values())
    for g in gains.values():
        assert 0.0 <= g <= hi + 1e-9


def test_state_is_garbage_collected_for_absent_ids():
    c = VoiceConductor(samplerate=44100, seed=1)
    c.update([1, 2], 1024)
    gains = c.update([2], 1024)
    assert set(gains) == {2}
    assert 1 not in c._gain


def test_gains_evolve_over_time():
    c = VoiceConductor(samplerate=44100, seed=1)
    first = c.update([1, 2, 3, 4, 5, 6, 7, 8], 1024)[1]
    last = first
    for _ in range(2000):                     # ~46 s at 1024/44100 per block
        last = c.update([1, 2, 3, 4, 5, 6, 7, 8], 1024)[1]
    assert abs(last - first) > 0.05           # the voice's gain has clearly moved


def test_per_block_gain_change_is_smoothed():
    c = VoiceConductor(samplerate=44100, seed=1)
    ids = list(range(1, 13))
    prev = c.update(ids, 1024)
    for _ in range(500):
        cur = c.update(ids, 1024)
        for vid in ids:
            assert abs(cur[vid] - prev[vid]) < 0.1   # no click-inducing jumps
        prev = cur


def test_deterministic_under_seed():
    a = VoiceConductor(samplerate=44100, seed=7)
    b = VoiceConductor(samplerate=44100, seed=7)
    for _ in range(50):
        assert a.update([1, 2, 3], 1024) == b.update([1, 2, 3], 1024)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `rtk python -m pytest tests/test_soundscape_conductor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'soundscape_conductor'`

- [ ] **Step 3: Write the implementation**

Create `audio_prototype/soundscape_conductor.py`:

```python
"""Slow evolving-mix conductor for the soundscape (feedback: ebb and flow
instead of a constant wall of sound). Produces a per-voice gain that fades
voices in and out over tens of seconds and rotates which voices sit in the
foreground, reusing the spec-9 role budgets. Deterministic given a seed."""

import numpy as np

from soundscape_density import ROLE_GAIN, assign_voice_roles


class VoiceConductor:
    def __init__(self, samplerate, seed=None, min_period=20.0, max_period=50.0,
                 swell_min=0.35, swell_depth=0.65, smooth_tau=0.6):
        self.samplerate = float(samplerate)
        self.seed = 0 if seed is None else int(seed)
        self.min_period = float(min_period)
        self.max_period = float(max_period)
        self.swell_min = float(swell_min)
        self.swell_depth = float(swell_depth)
        self.smooth_tau = float(smooth_tau)
        self._t = 0.0
        self._params = {}   # vid -> (rate_hz, phase)
        self._gain = {}     # vid -> smoothed gain

    def _params_for(self, vid):
        params = self._params.get(vid)
        if params is None:
            rng = np.random.default_rng(self.seed * 1_000_003 + int(vid))
            period = rng.uniform(self.min_period, self.max_period)
            phase = rng.uniform(0.0, 1.0)
            params = (1.0 / period, phase)
            self._params[vid] = params
        return params

    def _activity(self, vid):
        rate, phase = self._params_for(vid)
        return 0.5 + 0.5 * np.sin(2.0 * np.pi * (self._t * rate + phase))

    def update(self, active_ids, frames):
        active = list(active_ids)
        # GC state for voices that disappeared.
        keep = set(active)
        self._params = {v: p for v, p in self._params.items() if v in keep}
        self._gain = {v: g for v, g in self._gain.items() if v in keep}
        if not active:
            self._t += frames / self.samplerate
            return {}

        activity = {vid: float(self._activity(vid)) for vid in active}
        ranked = sorted(active, key=lambda v: activity[v], reverse=True)
        roles = assign_voice_roles(ranked)

        dt = frames / self.samplerate
        alpha = 1.0 - np.exp(-dt / self.smooth_tau)
        out = {}
        for vid in active:
            target = ROLE_GAIN[roles[vid]] * (self.swell_min + self.swell_depth * activity[vid])
            current = self._gain.get(vid, target)
            current += alpha * (target - current)
            self._gain[vid] = current
            out[vid] = current
        self._t += dt
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk python -m pytest tests/test_soundscape_conductor.py -v`
Expected: PASS (all 5)

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/soundscape_conductor.py audio_prototype/tests/test_soundscape_conductor.py
rtk git commit -m "feat(soundscape): VoiceConductor for slow evolving-mix gains"
```

---

### Task 3: Gliding root + conductor integration in `SoundscapeEngine`

Add a continuous, glide-smoothed harmonic root, and rewrite `generate_block` to (a) glide the root and re-pitch tonal voices each block and (b) use the conductor's gains instead of static role gains.

**Files:**
- Modify: `audio_prototype/soundscape_engine.py` (imports, `__init__`, add `set_root`, rewrite `generate_block`)
- Test: `audio_prototype/tests/test_soundscape_engine.py`

**Interfaces:**
- Consumes: `VoiceConductor` (Task 2); `soundscape_harmony.ROLE_SEMITONES`.
- Produces: `SoundscapeEngine.set_root(target_midi: float) -> None`; attributes `_root_target`, `_root_current` (floats). `generate_block` behavior unchanged in signature/return type.

- [ ] **Step 1: Write the failing tests**

```python
from soundscape_harmony import ROLE_SEMITONES


def test_set_root_glides_field_toward_target():
    engine = SoundscapeEngine(samplerate=44100, seed=1, root_midi=62)
    engine.connect_patch(hue=0.03, sat=0.68, val=0.94, bpm=90.0, source_preset="additive_2")
    engine.set_root(50.0)
    engine.generate_block(1024)
    after_one = engine._root_current
    assert 50.0 < after_one < 62.0                 # moved toward target, not instantly
    for _ in range(200):
        engine.generate_block(1024)
    assert abs(engine._root_current - 50.0) < 0.5   # converges


def test_root_change_reprices_tonal_voice_preserving_role_and_octave():
    engine = SoundscapeEngine(samplerate=44100, seed=1, root_midi=62)
    pid = engine.connect_patch(hue=0.03, sat=0.68, val=0.94, bpm=90.0, source_preset="additive_2")
    engine.generate_block(1024)                     # allocate + first render
    a = engine._assignments[pid]
    role, octave, detune = a.harmonic_role, a.octave, a.detune_cents
    midi_before = a.midi
    engine.set_root(74.0)                           # +12 semitones
    for _ in range(400):
        engine.generate_block(1024)
    a2 = engine._assignments[pid]
    assert a2.harmonic_role == role and a2.octave == octave and a2.detune_cents == detune
    expected = 74.0 + ROLE_SEMITONES[role] + 12 * octave + detune / 100.0
    assert abs(a2.midi - expected) < 0.01
    assert abs((a2.midi - midi_before) - 12.0) < 0.05


def test_set_root_does_not_add_or_remove_patches():
    engine = SoundscapeEngine(samplerate=44100, seed=1, root_midi=62)
    pid = engine.connect_patch(hue=0.03, sat=0.68, val=0.94, bpm=90.0, source_preset="additive_2")
    engine.set_root(48.0)
    engine.generate_block(1024)
    assert list(engine._patches.keys()) == [pid]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `rtk python -m pytest tests/test_soundscape_engine.py -k "glide or reprices or add_or_remove" -v`
Expected: FAIL (`set_root` missing / `_root_current` missing)

- [ ] **Step 3: Update imports and `__init__`**

At the top of `soundscape_engine.py`, extend the harmony import and add the conductor import:

```python
from soundscape_conductor import VoiceConductor
from soundscape_density import DensityGainSmoother, ROLE_GAIN, assign_voice_roles
from soundscape_harmony import HarmonicField, PitchAllocator, ROLE_SEMITONES
```

In `SoundscapeEngine.__init__`, after `self.gain_smoother = DensityGainSmoother()` add:

```python
        self.conductor = VoiceConductor(samplerate=samplerate, seed=seed)
        self._root_target = float(root_midi)
        self._root_current = float(root_midi)
```

- [ ] **Step 4: Add `set_root` and rewrite `generate_block`**

Add after `set_patch_transform`:

```python
    def set_root(self, target_midi):
        self._root_target = float(target_midi)
```

Replace the whole `generate_block` method with:

```python
    def generate_block(self, frames):
        patches = list(self._patches.values())
        active_ids = [p.id for p in patches]
        self.sources.sync(active_ids)
        self.transforms.sync(active_ids)

        # Glide the shared root toward its target (~0.4 s regardless of block
        # size) so a live slider re-pitches sounding voices smoothly.
        glide_k = 1.0 - np.exp(-(frames / self.samplerate) / 0.4)
        self._root_current += glide_k * (self._root_target - self._root_current)
        self.field.root_midi = self._root_current

        conductor_gains = self.conductor.update(active_ids, frames)
        if not patches:
            return np.zeros(frames, dtype=np.float32)

        density = min(1.0, len(patches) / 20.0)
        voice_gain = self.gain_smoother.update(len(patches))

        mix = np.zeros(frames, dtype=np.float64)
        for patch in patches:
            if patch.id not in self._assignments:
                detune_class = "granular" if patch.source_preset.startswith("granular") else "foreground"
                rng = np.random.default_rng(patch.id)
                self._assignments[patch.id] = self.allocator.allocate(patch.id, rng, density, detune_class)
            assignment = self._assignments[patch.id]
            # Re-derive pitch from the glided root, preserving the role, octave
            # and detune the allocator chose (parallel shift of all tonal voices).
            assignment.midi = (
                self._root_current
                + ROLE_SEMITONES[assignment.harmonic_role]
                + 12 * assignment.octave
                + assignment.detune_cents / 100.0
            )
            gain = conductor_gains.get(patch.id, 0.0)
            if gain <= 1e-6:
                continue
            voice = self.sources.render(
                patch.id, patch.source_preset, assignment,
                patch.hue, patch.sat, patch.val, patch.bpm, frames,
            )
            if patch.transform_preset:
                voice = self.transforms.render(patch.id, patch.transform_preset, voice, patch.bpm)
            mix += voice * gain * voice_gain

        mixed = self.limiter.process(mix.astype(np.float32))
        return soft_clip(mixed).astype(np.float32)
```

- [ ] **Step 5: Run the full engine suite to verify pass + no regressions**

Run: `rtk python -m pytest tests/test_soundscape_engine.py -v`
Expected: PASS (existing tests + the 3 new ones). The evolving gains keep one-voice RMS audible (`swell_min` floor 0.35), so `test_one_patch_is_audible_bounded_and_nan_free` still passes.

- [ ] **Step 6: Commit**

```bash
rtk git add audio_prototype/soundscape_engine.py audio_prototype/tests/test_soundscape_engine.py
rtk git commit -m "feat(soundscape): gliding live root + evolving-mix conductor in generate_block"
```

---

### Task 4: `SynthAudioEngine.set_root` (thread-safe)

Expose the live root to the UI thread with the engine's lock held.

**Files:**
- Modify: `audio_prototype/synth_audio_engine.py` (add `set_root`, update `root_midi` semantics)
- Test: `audio_prototype/tests/test_synth_audio_engine.py`

**Interfaces:**
- Consumes: `SoundscapeEngine.set_root` (Task 3).
- Produces: `SynthAudioEngine.set_root(target_midi: float) -> None`; `root_midi` property returns the current target as an `int` (rounded).

- [ ] **Step 1: Write the failing test**

```python
def test_set_root_updates_target_without_clearing_patches():
    eng = SynthAudioEngine(seed=1, root_midi=62)
    pid = eng.connect_patch(0.03, 0.68, 0.94, 90.0, "additive_2", None)
    eng.set_root(55.0)
    assert eng.root_midi == 55
    assert [p["id"] for p in eng.active_patches()] == [pid]   # patches survive
    assert eng.engine._root_target == 55.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk python -m pytest tests/test_synth_audio_engine.py::test_set_root_updates_target_without_clearing_patches -v`
Expected: FAIL (`set_root` missing on `SynthAudioEngine`)

- [ ] **Step 3: Implement**

In `synth_audio_engine.py`, change the `root_midi` property to read the engine's live target, and add `set_root`. Replace the existing property:

```python
    @property
    def root_midi(self):
        return int(round(self._root_target))
```

Add `self._root_target = float(self._root_midi)` in `__init__` right after `self._root_midi = int(root_midi)`. Then add, in the "sample + tuning" section (near `set_root_midi`):

```python
    def set_root(self, target_midi):
        with self._lock:
            self._root_target = float(target_midi)
            self.engine.set_root(target_midi)
```

Also, inside the existing `set_root_midi`, after `self._root_midi = int(root_midi)` add `self._root_target = float(root_midi)` so a full rebuild keeps the target consistent.

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk python -m pytest tests/test_synth_audio_engine.py::test_set_root_updates_target_without_clearing_patches -v`
Expected: PASS

- [ ] **Step 5: Run the whole synth-audio suite**

Run: `rtk python -m pytest tests/test_synth_audio_engine.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
rtk git add audio_prototype/synth_audio_engine.py audio_prototype/tests/test_synth_audio_engine.py
rtk git commit -m "feat(synth): thread-safe live set_root on SynthAudioEngine"
```

---

### Task 5: `SynthPatchModel` (pure tab state)

The non-Tk state machine for the web-app workflow: sources (single-use), voices, and generator-jack occupancy. Calls the engine to connect/disconnect/retarget.

**Files:**
- Modify: `audio_prototype/synth_tab.py` (add `SynthPatchModel` class near the geometry helpers, before the Tk imports section)
- Test: `audio_prototype/tests/test_synth_patch_model.py`

**Interfaces:**
- Consumes: engine methods `connect_patch(hue,sat,val,bpm,source_preset,transform_preset) -> pid`, `disconnect_patch(pid)`, `set_patch_transform(pid, transform_preset)`; helpers `source_preset_id(row,col)`, `transform_preset_id(row,col)`; constant `SYNTH_PATCH_LIMIT`.
- Produces:
  - `SynthPatchModel(engine, limit=SYNTH_PATCH_LIMIT)`
  - `add_source(hue,sat,val,bpm,color) -> int | None` (client id; `None` if at cap)
  - `remove_source(cid) -> None`
  - `assign_source_to_generator(cid, source_cell) -> int | None` (engine pid; `None` if source unknown; replaces an occupied jack)
  - `set_voice_transform(pid, transform_cell | None) -> None`
  - `remove_voice(pid) -> None`
  - `total_count() -> int`
  - public dict attributes: `sources` (`cid -> {hue,sat,val,bpm,color}`), `voices` (`pid -> {source_cell,transform_cell,color,bpm,source_id,transform_id,client_id}`), `jack_to_pid` (`source_cell -> pid`)

- [ ] **Step 1: Write the failing tests**

```python
from soundscape_engine import SoundscapeEngine
from synth_tab import SynthPatchModel, SYNTH_PATCH_LIMIT, source_preset_id, transform_preset_id


def _model():
    return SynthPatchModel(SoundscapeEngine(samplerate=44100, seed=1))


def test_send_then_assign_consumes_source_and_creates_source_only_voice():
    m = _model()
    cid = m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800")
    assert cid in m.sources
    pid = m.assign_source_to_generator(cid, (0, 1))     # additive_2
    assert cid not in m.sources                          # single-use: consumed
    assert m.voices[pid]["source_id"] == source_preset_id(0, 1)
    assert m.voices[pid]["transform_cell"] is None
    assert m.jack_to_pid[(0, 1)] == pid
    assert m.engine._patches[pid].transform_preset is None


def test_cable_generator_to_modifier_sets_and_clears_transform():
    m = _model()
    cid = m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800")
    pid = m.assign_source_to_generator(cid, (0, 0))
    m.set_voice_transform(pid, (2, 3))                   # pitch_4
    assert m.voices[pid]["transform_id"] == transform_preset_id(2, 3)
    assert m.engine._patches[pid].transform_preset == transform_preset_id(2, 3)
    m.set_voice_transform(pid, None)
    assert m.voices[pid]["transform_cell"] is None
    assert m.engine._patches[pid].transform_preset is None


def test_assign_onto_occupied_jack_replaces_previous_voice():
    m = _model()
    c1 = m.add_source(0.03, 0.68, 0.94, 90.0, "#ff0000")
    c2 = m.add_source(0.05, 0.68, 0.94, 90.0, "#ff8800")
    p1 = m.assign_source_to_generator(c1, (1, 1))
    p2 = m.assign_source_to_generator(c2, (1, 1))        # same jack
    assert p1 not in m.engine._patches                   # old voice disconnected
    assert m.jack_to_pid[(1, 1)] == p2
    assert len(m.voices) == 1


def test_remove_voice_frees_jack_and_disconnects():
    m = _model()
    cid = m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800")
    pid = m.assign_source_to_generator(cid, (3, 2))
    m.remove_voice(pid)
    assert pid not in m.engine._patches
    assert (3, 2) not in m.jack_to_pid
    assert pid not in m.voices


def test_combined_cap_counts_sources_plus_voices():
    m = _model()
    for _ in range(SYNTH_PATCH_LIMIT):
        assert m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800") is not None
    assert m.add_source(0.03, 0.68, 0.94, 90.0, "#ff8800") is None   # at cap
    assert m.total_count() == SYNTH_PATCH_LIMIT


def test_assign_unknown_source_returns_none():
    m = _model()
    assert m.assign_source_to_generator(999, (0, 0)) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `rtk python -m pytest tests/test_synth_patch_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'SynthPatchModel'`

- [ ] **Step 3: Implement**

In `synth_tab.py`, add this class after the pure geometry helpers (after `transform_cell_at`) and before the `import tkinter` block:

```python
class SynthPatchModel:
    """Pure state for the web-app-style synth workflow (no Tk): scanned
    sources are single-use; assigning one onto a generator jack consumes it
    and creates an engine voice; cabling that jack to a modifier sets the
    voice's transform. `engine` is a SoundscapeEngine / SynthAudioEngine."""

    def __init__(self, engine, limit=SYNTH_PATCH_LIMIT):
        self.engine = engine
        self.limit = limit
        self._next_client_id = 1
        self.sources = {}      # cid -> {hue,sat,val,bpm,color}
        self.voices = {}       # pid -> {source_cell,transform_cell,color,bpm,source_id,transform_id,client_id}
        self.jack_to_pid = {}  # source_cell -> pid

    def total_count(self):
        return len(self.sources) + len(self.voices)

    def add_source(self, hue, sat, val, bpm, color):
        if self.total_count() >= self.limit:
            return None
        cid = self._next_client_id
        self._next_client_id += 1
        self.sources[cid] = {"hue": hue, "sat": sat, "val": val, "bpm": bpm, "color": color}
        return cid

    def remove_source(self, cid):
        self.sources.pop(cid, None)

    def assign_source_to_generator(self, cid, source_cell):
        src = self.sources.get(cid)
        if src is None:
            return None
        occupant = self.jack_to_pid.get(source_cell)
        if occupant is not None:
            self.remove_voice(occupant)
        source_id = source_preset_id(*source_cell)
        pid = self.engine.connect_patch(
            src["hue"], src["sat"], src["val"], src["bpm"], source_id, None
        )
        self.voices[pid] = {
            "source_cell": source_cell,
            "transform_cell": None,
            "color": src["color"],
            "bpm": src["bpm"],
            "source_id": source_id,
            "transform_id": None,
            "client_id": cid,
        }
        self.jack_to_pid[source_cell] = pid
        del self.sources[cid]
        return pid

    def set_voice_transform(self, pid, transform_cell):
        voice = self.voices.get(pid)
        if voice is None:
            return
        transform_id = transform_preset_id(*transform_cell) if transform_cell is not None else None
        self.engine.set_patch_transform(pid, transform_id)
        voice["transform_cell"] = transform_cell
        voice["transform_id"] = transform_id

    def remove_voice(self, pid):
        voice = self.voices.pop(pid, None)
        if voice is None:
            return
        self.engine.disconnect_patch(pid)
        self.jack_to_pid.pop(voice["source_cell"], None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `rtk python -m pytest tests/test_synth_patch_model.py -v`
Expected: PASS (all 6)

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/synth_tab.py audio_prototype/tests/test_synth_patch_model.py
rtk git commit -m "feat(synth): SynthPatchModel pure state for the web-app workflow"
```

---

### Task 6: Rewrite the `SynthTab` widget for the web-app workflow

Send button + Sources list + click-assign + generator→modifier cabling + Play/Pause + live root slider, all driven through `SynthPatchModel`.

**Files:**
- Modify: `audio_prototype/synth_tab.py` (rewrite the `SynthTab` class body; keep all pure helpers and `SynthPatchModel`)
- Test: `audio_prototype/tests/test_synth_tab.py` (replace the Tk-widget interaction tests; keep the pure-helper tests)

**Interfaces:**
- Consumes: `SynthPatchModel` (Task 5); `SynthAudioEngine.set_root`/`resume`/`pause`/`paused` (Tasks 3–4); geometry helpers; `gui._patch_cable_points`, `gui._picker_coords_to_hsv`, `gui._random_scan_values`, `PICKER_W`, `PICKER_H`.
- Produces: `SynthTab(parent, synth_engine)` with attributes/methods used by tests: `model` (a `SynthPatchModel`), `_on_send()`, `_select_source(cid)`, `_selected_source_id`, `_on_press(event)`, `_on_release(event)`, `_on_toggle_play()`, `play_button`, `bpm_var`.

- [ ] **Step 1: Replace the Tk-widget tests**

In `tests/test_synth_tab.py`, delete the four old interaction tests (`test_drag_source_jack_to_transform_jack_creates_patch`, `test_release_off_transform_grid_makes_source_only_patch`, `test_press_off_source_grid_starts_no_cable`, `test_remove_patch_disconnects_voice`) and the `_Ev`/`_tk_root_or_skip` helpers stay. Add these tests (keep the existing pure-helper tests and geometry round-trip tests untouched):

```python
def test_send_then_click_assign_creates_source_only_voice():
    root = _tk_root_or_skip()
    try:
        eng = SynthAudioEngine(seed=1)
        tab = SynthTab(root, eng)
        tab.bpm_var.set("90")
        tab._on_send()
        cid = next(iter(tab.model.sources))
        tab._select_source(cid)
        gx, gy = source_cell_center(0, 1)              # additive_2
        tab._on_press(_Ev(gx, gy))
        tab._on_release(_Ev(gx, gy))                   # click, no drag
        patches = eng.active_patches()
        assert len(patches) == 1
        assert patches[0]["source_preset"] == "additive_2"
        assert patches[0]["transform_preset"] is None
        assert not tab.model.sources                   # source consumed
    finally:
        root.destroy()


def test_cable_from_placed_generator_jack_to_modifier_sets_transform():
    root = _tk_root_or_skip()
    try:
        eng = SynthAudioEngine(seed=1)
        tab = SynthTab(root, eng)
        tab.bpm_var.set("90")
        tab._on_send()
        cid = next(iter(tab.model.sources))
        tab._select_source(cid)
        gx, gy = source_cell_center(0, 0)
        tab._on_press(_Ev(gx, gy)); tab._on_release(_Ev(gx, gy))
        tab._on_press(_Ev(gx, gy))                     # press placed jack -> cable
        tx, ty = transform_cell_center(0, 0)           # delay_1
        tab._on_release(_Ev(tx, ty))
        assert eng.active_patches()[0]["transform_preset"] == "delay_1"
    finally:
        root.destroy()


def test_play_pause_toggles_engine():
    root = _tk_root_or_skip()
    try:
        eng = SynthAudioEngine(seed=1)
        tab = SynthTab(root, eng)
        assert eng.paused is True
        tab._on_toggle_play()
        assert eng.paused is False
        tab._on_toggle_play()
        assert eng.paused is True
    finally:
        eng.stop()
        root.destroy()
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `rtk python -m pytest tests/test_synth_tab.py -v`
Expected: FAIL (`_on_send` / `model` / `_select_source` / `_on_toggle_play` not defined)

- [ ] **Step 3: Rewrite the `SynthTab` class**

Replace the entire `SynthTab` class (from `class SynthTab:` to end of file) with the following. Keep the module-level constants (`WAVEFORM_WINDOW_SAMPLES`, `REFRESH_MS`) above it.

```python
class SynthTab:
    """Web-app-style synth workflow: scan a finger color + BPM, Send it into
    the Sources list, click a source then a generator jack to assign it
    (single-use), and drag a cable from that placed jack to a modifier jack.
    A Play/Pause button owns synth playback; a slider glides the harmonic
    root live. Drives a pure SynthPatchModel and the SynthAudioEngine."""

    def __init__(self, parent, synth_engine):
        self.parent = parent
        self.engine = synth_engine
        self.model = SynthPatchModel(synth_engine)
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill="both", expand=True)
        self.refresh_ms = REFRESH_MS

        self._selected_source_id = None
        self._source_rows = {}      # cid -> row frame
        self._voice_rows = {}       # pid -> row frame
        self._drag_from_pid = None  # cabling from a placed generator jack
        self._drag_pos = None

        self.hue_var = tk.DoubleVar(value=0.0)
        self.sat_var = tk.DoubleVar(value=0.75)
        self.val_var = tk.DoubleVar(value=0.64)
        self.bpm_var = tk.StringVar(value="70")
        self.root_label_var = tk.StringVar()

        self._build_controls()
        self._build_bay()
        self._build_sources_list()
        self._build_voice_list()
        self._build_waveform()
        self._schedule_refresh()

    # ---------- left controls ----------

    def _build_controls(self):
        panel = ttk.Frame(self.frame)
        panel.grid(row=0, column=0, sticky="nw", padx=8, pady=8)

        transport = ttk.Frame(panel)
        transport.pack(fill="x")
        self.play_button = ttk.Button(transport, text="Play", command=self._on_toggle_play)
        self.play_button.pack(fill="x")

        colorbox = ttk.LabelFrame(panel, text="Scan input - finger color + BPM")
        colorbox.pack(fill="x", pady=(8, 0))
        self.picker = tk.Canvas(
            colorbox, width=PICKER_W, height=PICKER_H, highlightthickness=1, cursor="cross"
        )
        self.picker.grid(row=0, column=0, columnspan=3, sticky="w")
        self._picker_image = self._build_picker_image()
        self.picker.create_image(0, 0, anchor="nw", image=self._picker_image)
        self._marker = self.picker.create_oval(0, 0, 0, 0, outline="white", width=2)
        self.picker.bind("<Button-1>", lambda e: self._set_pick(e.x, e.y))
        self.picker.bind("<B1-Motion>", lambda e: self._set_pick(e.x, e.y))
        ttk.Label(colorbox, text="BPM").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(colorbox, textvariable=self.bpm_var, width=8).grid(
            row=1, column=1, sticky="w", pady=(6, 0)
        )
        self.swatch = tk.Canvas(colorbox, width=40, height=40, highlightthickness=1)
        self.swatch.grid(row=1, column=2, padx=8)
        ttk.Button(colorbox, text="Random", command=self._on_random).grid(
            row=2, column=0, sticky="ew", pady=(8, 0)
        )
        ttk.Button(colorbox, text="Send", command=self._on_send).grid(
            row=2, column=1, sticky="ew", pady=(8, 0)
        )

        rootbox = ttk.LabelFrame(panel, text="Harmonic root (live)")
        rootbox.pack(fill="x", pady=(8, 0))
        lo = ROOT_NOTE_CHOICES[0][1]
        hi = ROOT_NOTE_CHOICES[-1][1]
        self._root_min, self._root_max = lo, hi
        self.root_scale = ttk.Scale(
            rootbox, from_=lo, to=hi, orient="horizontal", command=self._on_root_slider
        )
        self.root_scale.set(self.engine.root_midi)
        self.root_scale.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        rootbox.columnconfigure(0, weight=1)
        self._update_root_label(self.engine.root_midi)
        ttk.Label(rootbox, textvariable=self.root_label_var, width=6).grid(row=0, column=1, padx=4)

        ttk.Button(panel, text="Load Sample...", command=self._on_load_sample).pack(
            fill="x", pady=(8, 0)
        )
        self._set_pick(PICKER_W // 2, PICKER_H // 2)

    def _build_picker_image(self):
        img = tk.PhotoImage(width=PICKER_W, height=PICKER_H)
        rows = []
        for y in range(PICKER_H):
            row = []
            for x in range(PICKER_W):
                hue, sat, val = _picker_coords_to_hsv(x, y)
                r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
                row.append(f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}")
            rows.append("{" + " ".join(row) + "}")
        img.put(" ".join(rows))
        return img

    def _set_pick(self, x, y):
        x = int(min(PICKER_W - 1, max(0, x)))
        y = int(min(PICKER_H - 1, max(0, y)))
        hue, sat, val = _picker_coords_to_hsv(x, y)
        self.hue_var.set(hue)
        self.sat_var.set(sat)
        self.val_var.set(val)
        self.picker.coords(self._marker, x - 5, y - 5, x + 5, y + 5)
        self.swatch.configure(bg=self._color_hex())

    def _color_hex(self):
        r, g, b = colorsys.hsv_to_rgb(
            self.hue_var.get(), self.sat_var.get(), self.val_var.get()
        )
        return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))

    def _on_random(self):
        x, y, bpm = _random_scan_values()
        self._set_pick(x, y)
        self.bpm_var.set(f"{bpm:.0f}")

    def _on_root_slider(self, value):
        midi = float(value)
        self.engine.set_root(midi)
        self._update_root_label(midi)

    def _update_root_label(self, midi):
        nearest = int(round(float(midi)))
        label = next((lbl for lbl, m in ROOT_NOTE_CHOICES if m == nearest), str(nearest))
        self.root_label_var.set(label)

    def _on_load_sample(self):
        path = filedialog.askopenfilename(
            filetypes=[("Audio files", "*.wav *.mp3"), ("WAV files", "*.wav")]
        )
        if not path:
            return
        try:
            self.engine.load_sample(path)
        except Exception as exc:
            messagebox.showerror("Failed to load sample", str(exc))

    # ---------- transport ----------

    def _on_toggle_play(self):
        if self.engine.paused:
            try:
                self.engine.resume()
            except Exception as exc:
                messagebox.showerror("Synth audio", f"Could not start synth audio: {exc}")
                return
        else:
            self.engine.pause()
        self._sync_play_button()

    def _sync_play_button(self):
        self.play_button.configure(text="Play" if self.engine.paused else "Pause")

    # ---------- send + sources ----------

    def _on_send(self):
        if self.model.total_count() >= self.model.limit:
            messagebox.showinfo("Sources full", f"Maximum voices reached ({self.model.limit}).")
            return
        bpm = parse_bpm(self.bpm_var.get())
        if bpm is None:
            messagebox.showerror("Invalid BPM", f"BPM must be a number ({self.bpm_var.get()!r}).")
            return
        cid = self.model.add_source(
            self.hue_var.get(), self.sat_var.get(), self.val_var.get(), bpm, self._color_hex()
        )
        if cid is not None:
            self._add_source_row(cid)

    def _build_sources_list(self):
        box = ttk.LabelFrame(self.frame, text="Sources - click one, then click a generator jack")
        box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.sources_frame = ttk.Frame(box)
        self.sources_frame.pack(fill="both", expand=True)

    def _add_source_row(self, cid):
        src = self.model.sources[cid]
        row = ttk.Frame(self.sources_frame)
        row.pack(fill="x", pady=2)
        tk.Canvas(row, width=16, height=16, highlightthickness=1, bg=src["color"]).pack(
            side="left", padx=(0, 6)
        )
        btn = ttk.Button(
            row, text=f"{src['bpm']:.0f} BPM", width=12, command=lambda: self._select_source(cid)
        )
        btn.pack(side="left", padx=(0, 8))
        ttk.Button(row, text="Remove", command=lambda: self._remove_source(cid)).pack(side="right")
        self._source_rows[cid] = row
        self._refresh_source_selection()

    def _select_source(self, cid):
        self._selected_source_id = cid
        self._refresh_source_selection()

    def _refresh_source_selection(self):
        for cid, row in self._source_rows.items():
            state = "selected" if cid == self._selected_source_id else "normal"
            for child in row.winfo_children():
                if isinstance(child, tk.Canvas):
                    child.configure(highlightbackground="white" if state == "selected" else "#888")

    def _remove_source(self, cid):
        self.model.remove_source(cid)
        row = self._source_rows.pop(cid, None)
        if row is not None:
            row.destroy()
        if self._selected_source_id == cid:
            self._selected_source_id = None

    # ---------- patch bay ----------

    def _build_bay(self):
        box = ttk.LabelFrame(
            self.frame, text="Patch bay - assign a source to a generator, then cable it to a modifier"
        )
        box.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        self.frame.columnconfigure(1, weight=1)
        self.frame.rowconfigure(0, weight=1)
        self.bay = tk.Canvas(
            box, width=SYNTH_CANVAS_W, height=SYNTH_CANVAS_H, bg="#161616", highlightthickness=0
        )
        self.bay.pack(fill="both", expand=True)
        self.bay.bind("<Button-1>", self._on_press)
        self.bay.bind("<B1-Motion>", self._on_drag)
        self.bay.bind("<ButtonRelease-1>", self._on_release)
        self._redraw_bay()

    def _draw_grid(self, origin, rows, title):
        ox, oy = origin
        c = self.bay
        c.create_text(ox, oy - 22, text=title, anchor="w", fill="#bdbdbd", font=("TkDefaultFont", 9))
        for r, name in enumerate(rows):
            cy = oy + r * SYNTH_CELL + SYNTH_CELL / 2
            c.create_text(ox - 10, cy, text=name, anchor="e", fill="#d5d5d5", font=("TkDefaultFont", 9))
            for col in range(SYNTH_GRID_SIZE):
                x0 = ox + col * SYNTH_CELL
                y0 = oy + r * SYNTH_CELL
                c.create_rectangle(x0, y0, x0 + SYNTH_CELL, y0 + SYNTH_CELL, outline="#444", fill="#222")
                c.create_text(x0 + 8, y0 + 10, text=VARIANT_LABELS[col], fill="#808080", font=("TkDefaultFont", 8))

    def _draw_jacks(self, origin, filled):
        for r in range(SYNTH_GRID_SIZE):
            for col in range(SYNTH_GRID_SIZE):
                cx, cy = _cell_center(origin, r, col)
                color = filled.get((r, col), "#3a3a3a")
                self.bay.create_oval(
                    cx - SYNTH_JACK_RADIUS, cy - SYNTH_JACK_RADIUS,
                    cx + SYNTH_JACK_RADIUS, cy + SYNTH_JACK_RADIUS,
                    outline="#8a8a8a", fill=color, width=2,
                )

    def _redraw_bay(self):
        c = self.bay
        c.delete("all")
        self._draw_grid(SYNTH_SOURCE_ORIGIN, SYNTH_SOURCE_ROWS, "generators")
        self._draw_grid(SYNTH_TRANSFORM_ORIGIN, SYNTH_TRANSFORM_ROWS, "modifiers")

        source_fill = {}
        transform_fill = {}
        for voice in self.model.voices.values():
            source_fill[voice["source_cell"]] = voice["color"]
            if voice["transform_cell"] is not None:
                transform_fill[voice["transform_cell"]] = voice["color"]

        for voice in self.model.voices.values():
            sx, sy = source_cell_center(*voice["source_cell"])
            if voice["transform_cell"] is not None:
                tx, ty = transform_cell_center(*voice["transform_cell"])
                c.create_line(*_patch_cable_points(sx, sy, tx, ty), fill=voice["color"], width=3)
            else:
                c.create_line(sx, sy, sx + 18, sy, fill=voice["color"], width=3)

        if self._drag_from_pid is not None and self._drag_pos is not None:
            voice = self.model.voices.get(self._drag_from_pid)
            if voice is not None:
                sx, sy = source_cell_center(*voice["source_cell"])
                c.create_line(*_patch_cable_points(sx, sy, *self._drag_pos),
                              fill=voice["color"], width=2, dash=(4, 3))

        self._draw_jacks(SYNTH_SOURCE_ORIGIN, source_fill)
        self._draw_jacks(SYNTH_TRANSFORM_ORIGIN, transform_fill)

    def _on_press(self, event):
        self._drag_from_pid = None
        self._drag_pos = None
        cell = source_cell_at(event.x, event.y)
        if cell is not None and cell in self.model.jack_to_pid:
            # press on a placed generator jack -> begin a modifier cable
            self._drag_from_pid = self.model.jack_to_pid[cell]

    def _on_drag(self, event):
        if self._drag_from_pid is None:
            return
        self._drag_pos = (event.x, event.y)
        self._redraw_bay()

    def _on_release(self, event):
        if self._drag_from_pid is not None:
            pid = self._drag_from_pid
            self._drag_from_pid = None
            self._drag_pos = None
            transform_cell = transform_cell_at(event.x, event.y)
            self.model.set_voice_transform(pid, transform_cell)
            self._redraw_bay()
            return
        # no cable in progress: click-assign the selected source onto a generator jack
        cell = source_cell_at(event.x, event.y)
        if cell is not None and self._selected_source_id is not None:
            cid = self._selected_source_id
            pid = self.model.assign_source_to_generator(cid, cell)
            if pid is not None:
                self._selected_source_id = None
                row = self._source_rows.pop(cid, None)
                if row is not None:
                    row.destroy()
                self._add_voice_row(pid)
                self._redraw_bay()

    # ---------- voice list ----------

    def _build_voice_list(self):
        box = ttk.LabelFrame(self.frame, text="Active voices")
        box.grid(row=1, column=1, sticky="nsew", padx=8, pady=(0, 8))
        canvas = tk.Canvas(box, height=120, highlightthickness=0)
        scrollbar = ttk.Scrollbar(box, orient="vertical", command=canvas.yview)
        self.voice_list_frame = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=self.voice_list_frame, anchor="nw")
        self.voice_list_frame.bind(
            "<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _add_voice_row(self, pid):
        voice = self.model.voices[pid]
        row = ttk.Frame(self.voice_list_frame)
        row.pack(fill="x", pady=2)
        tk.Canvas(row, width=16, height=16, highlightthickness=1, bg=voice["color"]).pack(
            side="left", padx=(0, 6)
        )
        label = f"#{pid}  {voice['source_id']}  (BPM {voice['bpm']:.0f})"
        lbl = ttk.Label(row, text=label)
        lbl.pack(side="left", padx=(0, 8))
        voice["_label_widget"] = lbl
        ttk.Button(row, text="Remove", command=lambda: self._remove_voice(pid)).pack(side="right")
        self._voice_rows[pid] = row

    def _remove_voice(self, pid):
        self.model.remove_voice(pid)
        row = self._voice_rows.pop(pid, None)
        if row is not None:
            row.destroy()
        self._redraw_bay()

    # ---------- waveform ----------

    def _build_waveform(self):
        box = ttk.LabelFrame(self.frame, text="Waveform")
        box.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0, 8))
        self.wave = tk.Canvas(box, height=110, bg="#0b0b0b", highlightthickness=0)
        self.wave.pack(fill="both", expand=True)
        self.wave_line = self.wave.create_line(0, 0, 0, 0, fill="#4da6ff", width=1)

    def _draw_wave(self):
        data = self.engine.visual_buffer.read_latest(WAVEFORM_WINDOW_SAMPLES)
        w = max(2, self.wave.winfo_width())
        h = max(2, self.wave.winfo_height())
        n = WAVEFORM_POINTS
        seg = max(1, len(data) // n)
        pts = []
        for i in range(n):
            chunk = data[i * seg:(i + 1) * seg]
            if len(chunk) == 0:
                v = 0.0
            else:
                v = float(chunk[int(np.argmax(np.abs(chunk)))])
            x = i / (n - 1) * w
            y = h / 2 - v * (h / 2 - 2)
            pts.extend((x, y))
        if len(pts) >= 4:
            self.wave.coords(self.wave_line, *pts)

    def _schedule_refresh(self):
        if self.frame.winfo_viewable():
            self._draw_wave()
            self._sync_play_button()
        self.parent.after(self.refresh_ms, self._schedule_refresh)
```

- [ ] **Step 4: Run the synth-tab suite**

Run: `rtk python -m pytest tests/test_synth_tab.py -v`
Expected: PASS (pure-helper + geometry tests unchanged; the 3 new interaction tests pass; skipped if no display).

- [ ] **Step 5: Commit**

```bash
rtk git add audio_prototype/synth_tab.py audio_prototype/tests/test_synth_tab.py
rtk git commit -m "feat(synth): web-app workflow UI (Send, Sources, click-assign, cable, Play/Pause, root slider)"
```

---

### Task 7: `gui.py` — Synth tab no longer force-resumes audio

The Play/Pause button now owns synth playback, so entering the Synth tab should open paused.

**Files:**
- Modify: `audio_prototype/gui.py:466-486` (`_on_tab_changed`)
- Test: manual (the change removes an auto-resume; covered behaviorally by Task 6's Play/Pause test).

**Interfaces:**
- Consumes: `SynthAudioEngine.pause()` / `resume()` / `paused`.
- Produces: no new API.

- [ ] **Step 1: Replace `_on_tab_changed`**

Replace the method body with:

```python
    def _on_tab_changed(self, _event):
        tab = self.notebook.tab(self.notebook.select(), "text")
        if tab == "Synth":
            # The Synth tab's own Play/Pause button owns synth playback; entering
            # the tab just hands the audio device over (loop paused, synth silent
            # until the user presses Play).
            self._loop_was_playing_before_synth = not self.engine.paused
            self.engine.pause()
            self.pause_button.configure(text="Play")
            self.synth_engine.pause()
        else:
            self.synth_engine.pause()
            if self._loop_was_playing_before_synth:
                self.engine.resume()
                self.pause_button.configure(text="Pause")
            else:
                self.pause_button.configure(text="Play")
```

- [ ] **Step 2: Run the gui + full suite to check for regressions**

Run: `rtk python -m pytest tests/test_gui.py -v`
Expected: PASS (no test asserted the old auto-resume; if one does, update it to expect `synth_engine.paused` after entering the Synth tab).

- [ ] **Step 3: Run the entire test suite**

Run: `rtk python -m pytest -q`
Expected: PASS (all green; Tk tests skip without a display).

- [ ] **Step 4: Commit**

```bash
rtk git add audio_prototype/gui.py
rtk git commit -m "feat(synth): Synth tab opens paused; Play/Pause button owns playback"
```

---

### Task 8: Manual smoke check + brief brief update

**Files:**
- Modify: `AGENTS.md` ("Pick up here" section)

- [ ] **Step 1: Launch and verify by ear**

Run: `cd audio_prototype && rtk python main.py`
Verify: switch to Synth; pick a color + BPM; **Send** adds a swatch to Sources; click it, click a generator jack → it sounds only after **Play**; drag from that jack to a modifier → timbre changes; add several voices and confirm the mix ebbs/flows rather than a flat wall; drag the root slider and hear all tonal voices glide in pitch.

- [ ] **Step 2: Update the brief**

Update `AGENTS.md`'s "⏱ Pick up here" Status/Last session/Next up to record the new web-app-parity workflow, the evolving-mix conductor, and the live gliding root slider.

- [ ] **Step 3: Commit**

```bash
rtk git add AGENTS.md
rtk git commit -m "docs: record synth web-app parity + evolving mix + live root in brief"
```
```

## Self-Review

**Spec coverage:**
- Component 1 (web-app workflow: Send/Sources/assign/cable/single-use/Play-Pause) → Tasks 5, 6, 7. ✅
- Component 2 (evolving-mix conductor) → Tasks 2, 3. ✅
- Component 3 (live gliding root slider) → Tasks 3, 4, 6. ✅
- `set_patch_transform` → Task 1. ✅
- `gui.py` tab-switch change → Task 7. ✅
- Tests for all new pure logic (conductor, engine glide, `set_patch_transform`, `SynthPatchModel`) → Tasks 1–6. ✅

**Placeholder scan:** No TBD/TODO; every code step shows full code; tests are concrete.

**Type consistency:** `VoiceConductor.update(active_ids, frames) -> dict` used consistently (Tasks 2, 3). `set_patch_transform(pid, transform_preset)` consistent (Tasks 1, 5). `SynthPatchModel` method names (`add_source`, `assign_source_to_generator`, `set_voice_transform`, `remove_voice`, `total_count`) match between Task 5 definition and Task 6 usage. `set_root(target_midi)` consistent (Tasks 3, 4, 6). `_on_send`/`_select_source`/`_on_toggle_play`/`play_button`/`model` match between Task 6 tests and implementation.
