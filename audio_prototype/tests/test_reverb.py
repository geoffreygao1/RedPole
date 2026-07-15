import numpy as np

from reverb import OnePoleLowpass, SchroederReverb

SR = 44100


def _tone(freq, n=8192, sr=SR):
    return np.sin(2 * np.pi * freq * np.arange(n) / sr)


def test_lowpass_attenuates_highs_more_than_lows():
    lp_low = OnePoleLowpass(SR, cutoff_hz=1000.0)
    lp_high = OnePoleLowpass(SR, cutoff_hz=1000.0)
    low_out = lp_low.process(_tone(100.0))
    high_out = lp_high.process(_tone(8000.0))
    # skip the settle-in region
    assert np.abs(high_out[4000:]).max() < np.abs(low_out[4000:]).max() * 0.5


def test_lowpass_cutoff_is_adjustable():
    lp = OnePoleLowpass(SR, cutoff_hz=500.0)
    dark = lp.process(_tone(4000.0))
    lp2 = OnePoleLowpass(SR, cutoff_hz=8000.0)
    bright = lp2.process(_tone(4000.0))
    assert np.abs(dark[4000:]).max() < np.abs(bright[4000:]).max()


def test_reverb_feedback_and_cutoff_setters():
    rv = SchroederReverb(SR)
    rv.set_feedback(0.9)
    assert all(c.feedback == 0.9 for c in rv._combs)
    rv.set_cutoff(1200.0)
    assert rv._lowpass.cutoff_hz == 1200.0


def test_space_style_changes_early_reflection_character():
    impulse = np.zeros(16384, dtype=np.float32)
    impulse[0] = 1.0

    room = SchroederReverb(SR)
    room.set_space(style="bright_room", size=0.2, diffusion=0.2)
    room_out = room.process(impulse)

    ambient = SchroederReverb(SR)
    ambient.set_space(style="ambient", size=1.0, diffusion=1.0)
    ambient_out = ambient.process(impulse)

    assert ambient.space_style == "ambient"
    assert ambient.space_size == 1.0
    assert ambient.diffusion == 1.0
    assert not np.allclose(room_out, ambient_out)
    assert float(np.sum(ambient_out[9000:] ** 2)) > float(
        np.sum(room_out[9000:] ** 2)
    )


def test_wash_space_has_later_denser_reflections_than_ambient():
    impulse = np.zeros(SR, dtype=np.float32)
    impulse[0] = 1.0

    ambient = SchroederReverb(SR)
    ambient.set_space(style="ambient", size=1.0, diffusion=1.0)
    ambient_out = ambient.process(impulse)

    wash = SchroederReverb(SR)
    wash.set_space(style="wash", size=1.0, diffusion=1.0)
    wash_out = wash.process(impulse)

    late = slice(int(0.45 * SR), int(0.95 * SR))
    assert wash.space_style == "wash"
    assert np.sum(wash_out[late] ** 2) > np.sum(ambient_out[late] ** 2) * 1.4


def test_reverb_wet_output_has_predelay_not_direct_dry_impulse():
    rv = SchroederReverb(SR)
    rv.set_space(style="ambient", size=1.0, diffusion=1.0)
    impulse = np.zeros(4096, dtype=np.float32)
    impulse[0] = 1.0

    out = rv.process(impulse)

    assert np.max(np.abs(out[:256])) < 1e-4
    assert np.max(np.abs(out[256:])) > 1e-4


def test_lower_feedback_decays_faster():
    def tail_energy(feedback):
        rv = SchroederReverb(SR)
        rv.set_feedback(feedback)
        impulse = np.zeros(1024, dtype=np.float32)
        impulse[0] = 1.0
        rv.process(impulse)
        silent = np.zeros(1024, dtype=np.float32)
        return sum(
            float(np.sum(rv.process(silent) ** 2)) for _ in range(40)
        )

    assert tail_energy(0.72) < tail_energy(0.92) * 0.5


def test_ambient_high_feedback_tail_stays_audible_for_seconds():
    rv = SchroederReverb(SR)
    rv.set_space(style="ambient", size=1.0, diffusion=1.0)
    rv.set_feedback(0.98)
    noise = np.random.default_rng(1).normal(0.0, 0.2, SR).astype(np.float32)

    for start in range(0, len(noise), 1024):
        rv.process(noise[start:start + 1024])

    tail_rms = []
    for _ in range(180):
        out = rv.process(np.zeros(1024, dtype=np.float32))
        tail_rms.append(float(np.sqrt(np.mean(out**2))))

    assert tail_rms[86] > 0.02
    assert tail_rms[129] > 0.01


def test_wash_high_feedback_tail_stays_audible_longer_than_ambient():
    def tail_at(style, feedback):
        rv = SchroederReverb(SR)
        rv.set_space(style=style, size=1.0, diffusion=1.0)
        rv.set_feedback(feedback)
        noise = np.random.default_rng(1).normal(0.0, 0.2, SR).astype(np.float32)
        for start in range(0, len(noise), 1024):
            rv.process(noise[start:start + 1024])
        tail = []
        for _ in range(260):
            out = rv.process(np.zeros(1024, dtype=np.float32))
            tail.append(float(np.sqrt(np.mean(out**2))))
        return tail

    ambient_tail = tail_at("ambient", 0.98)
    wash_tail = tail_at("wash", 0.992)

    assert wash_tail[215] > ambient_tail[215] * 1.6
    assert wash_tail[215] > 0.008


def test_silence_in_silence_out_from_clean_state():
    rv = SchroederReverb(SR)
    out = rv.process(np.zeros(1024, dtype=np.float32))
    np.testing.assert_allclose(out, np.zeros(1024))
    assert out.dtype == np.float32


def test_output_length_matches_input():
    rv = SchroederReverb(SR)
    assert rv.process(np.zeros(300, dtype=np.float32)).shape == (300,)
    assert rv.process(np.zeros(5000, dtype=np.float32)).shape == (5000,)


def test_impulse_produces_decaying_tail():
    rv = SchroederReverb(SR)
    impulse = np.zeros(1024, dtype=np.float32)
    impulse[0] = 1.0
    rv.process(impulse)

    silent = np.zeros(1024, dtype=np.float32)
    # tail energy per block over the next ~1.4 seconds
    energies = []
    for _ in range(60):
        out = rv.process(silent)
        energies.append(float(np.sum(out**2)))

    # tail exists well past 0.5s (block 22 is ~0.51-0.53s after impulse)
    assert energies[22] > 0.0
    # and decays: late tail is much quieter than early tail
    early = sum(energies[:10])
    late = sum(energies[50:60])
    assert late < early * 0.5
    assert early > 0.0


def test_state_persists_across_odd_block_sizes():
    rv = SchroederReverb(SR)
    impulse = np.zeros(300, dtype=np.float32)
    impulse[0] = 1.0
    rv.process(impulse)
    total = np.concatenate([rv.process(np.zeros(300, dtype=np.float32)) for _ in range(300)])
    assert np.max(np.abs(total)) > 0.0
