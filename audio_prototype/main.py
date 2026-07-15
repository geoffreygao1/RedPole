import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from audio_engine import AudioEngine
from gui import RedPoleGUI

DEFAULT_LOOP_PATH = Path(__file__).parent / "assets" / "sample_loop.wav"


def main():
    engine = AudioEngine()
    root = tk.Tk()
    try:
        RedPoleGUI(root, engine, str(DEFAULT_LOOP_PATH))
    except Exception as exc:
        messagebox.showerror("RedPole Audio Prototype", f"Failed to start: {exc}")
        sys.exit(1)
    root.mainloop()
    engine.stop()


if __name__ == "__main__":
    main()
