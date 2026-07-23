import numpy as np
import soundfile as sf

from soundscape_instruments import (
    INSTRUMENT_GRID,
    INSTRUMENT_MIDIS,
    INSTRUMENT_PRESETS,
    InstrumentBank,
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
