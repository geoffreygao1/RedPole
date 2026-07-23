import pytest

import main as app


class _MainStubEngine:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_main_stops_both_engines_when_gui_start_fails(monkeypatch):
    loop = _MainStubEngine()
    synth = _MainStubEngine()

    monkeypatch.setattr(app, "AudioEngine", lambda: loop)
    monkeypatch.setattr(app, "SynthAudioEngine", lambda: synth)
    monkeypatch.setattr(app.tk, "Tk", lambda: object())
    monkeypatch.setattr(
        app,
        "RedPoleGUI",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(app.messagebox, "showerror", lambda *_args, **_kwargs: None)

    with pytest.raises(SystemExit):
        app.main()

    assert loop.stopped is True
    assert synth.stopped is True
