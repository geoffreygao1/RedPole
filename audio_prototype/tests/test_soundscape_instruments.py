import numpy as np
import soundfile as sf
from types import SimpleNamespace

from soundscape_instruments import (
    INSTRUMENT_GRID,
    INSTRUMENT_MIDIS,
    INSTRUMENT_PRESETS,
    InstrumentBank,
    InstrumentSource,
)


def test_note_maps_and_presets_are_consistent():
    assert INSTRUMENT_MIDIS["piano"] == (48, 60, 72, 84)
    assert INSTRUMENT_MIDIS["tapeguitar"] == (36, 48, 60)
    # 3 behavior rows x 5 instruments = 15 presets
    assert len(INSTRUMENT_PRESETS) == 15
    rows = {p["behavior"] for p in INSTRUMENT_PRESETS}
    assert rows == {"pluck", "pad", "bloom"}
    for p in INSTRUMENT_PRESETS:
        assert p["engine"] == "instrument"
        assert p["row"] == p["behavior"]
        assert p["instrument"] in INSTRUMENT_MIDIS
    # column order per behavior matches INSTRUMENT_GRID
    for behavior, insts in INSTRUMENT_GRID.items():
        got = [p["instrument"] for p in INSTRUMENT_PRESETS if p["behavior"] == behavior]
        assert got == insts


def test_missing_assets_dir_yields_empty_bank(tmp_path):
    bank = InstrumentBank(samplerate=44100, assets_dir=str(tmp_path))
    assert bank.has("piano") is False
    assert bank.nearest("piano", 60) is None


def test_loads_wavs_and_nearest_picks_closest(tmp_path):
    sr = 44100
    for midi, freq in [(48, 100.0), (72, 400.0)]:
        t = np.arange(sr // 10) / sr
        sf.write(str(tmp_path / f"piano_{midi}.wav"),
                 (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32), sr)
    bank = InstrumentBank(samplerate=sr, assets_dir=str(tmp_path))
    assert bank.has("piano") is True
    sample, src = bank.nearest("piano", 55)     # closer to 48
    assert src == 48
    sample, src = bank.nearest("piano", 66)     # closer to 72
    assert src == 72
    assert float(np.max(np.abs(sample))) <= 1.0 + 1e-6


def test_samples_kwarg_bypasses_disk():
    data = {"flute": {60: np.ones(100, dtype=np.float64)}}
    bank = InstrumentBank(samplerate=44100, samples=data)
    assert bank.has("flute") is True
    sample, src = bank.nearest("flute", 90)
    assert src == 60 and len(sample) == 100


def _sustained_bank():
    # 1 second of a steady tone so pad/bloom have something to loop.
    sr = 44100
    t = np.arange(sr) / sr
    tone = 0.6 * np.sin(2 * np.pi * 220.0 * t)
    return InstrumentBank(samplerate=sr, samples={
        "strings": {60: tone.astype(np.float64)},
        "piano": {60: tone.astype(np.float64)},
    })


def test_pad_is_continuous_and_bounded():
    src = InstrumentSource(_sustained_bank(), samplerate=44100, seed=1)
    preset = {"instrument": "strings", "behavior": "pad"}
    a = SimpleNamespace(midi=60.0)
    total = np.concatenate([src.render(1, preset, a, 90.0, 1024) for _ in range(40)])
    assert not np.any(np.isnan(total))
    assert np.max(np.abs(total)) <= 1.0 + 1e-6
    assert float(np.sqrt(np.mean(total ** 2))) > 0.02   # audible, not silent


def test_pluck_is_mostly_silent_with_bursts():
    src = InstrumentSource(_sustained_bank(), samplerate=44100, seed=1)
    preset = {"instrument": "piano", "behavior": "pluck"}
    a = SimpleNamespace(midi=60.0)
    total = np.concatenate([src.render(1, preset, a, 90.0, 1024) for _ in range(200)])
    assert np.max(np.abs(total)) <= 1.0 + 1e-6
    frac_silent = float(np.mean(np.abs(total) < 1e-4))
    assert frac_silent > 0.2         # clearly gaps between notes
    assert float(np.sqrt(np.mean(total ** 2))) > 0.005   # but it does sound


def test_playback_rate_tracks_pitch():
    src = InstrumentSource(_sustained_bank(), samplerate=44100, seed=1)
    preset = {"instrument": "strings", "behavior": "pad"}
    lo = src.render(1, preset, SimpleNamespace(midi=48.0), 90.0, 2048)
    src2 = InstrumentSource(_sustained_bank(), samplerate=44100, seed=1)
    hi = src2.render(2, preset, SimpleNamespace(midi=72.0), 90.0, 2048)
    # higher pitch advances the read head faster -> voice pos larger
    assert src2._voices[2]["pos"] > src._voices[1]["pos"]


def test_empty_bank_is_silent_and_state_gcs():
    src = InstrumentSource(InstrumentBank(samplerate=44100, samples={}), 44100, seed=1)
    preset = {"instrument": "strings", "behavior": "pad"}
    out = src.render(1, preset, SimpleNamespace(midi=60.0), 90.0, 512)
    np.testing.assert_allclose(out, np.zeros(512))
    # sustained bank voice is GC'd when it stops being active
    src2 = InstrumentSource(_sustained_bank(), 44100, seed=1)
    src2.render(1, {"instrument": "strings", "behavior": "pad"}, SimpleNamespace(midi=60.0), 90.0, 512)
    src2.sync([2])
    assert 1 not in src2._voices
