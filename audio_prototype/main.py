import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from audio_engine import AudioEngine
from gui import RedPoleGUI
from synth_audio_engine import SynthAudioEngine

DEFAULT_LOOP_PATH = Path(__file__).parent / "assets" / "sample_loop.wav"


def main():
    engine = AudioEngine()
    synth_engine = SynthAudioEngine()
    root = tk.Tk()
    try:
        RedPoleGUI(root, engine, synth_engine, str(DEFAULT_LOOP_PATH))
        root.mainloop()
    except Exception as exc:
        messagebox.showerror("RedPole Audio Prototype", f"Failed to start: {exc}")
        sys.exit(1)
    finally:
        engine.stop()
        synth_engine.stop()


if __name__ == "__main__":
    main()
