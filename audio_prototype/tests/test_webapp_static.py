from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_loop_mode_cannot_post_play_before_loop_is_loaded():
    main_js = (ROOT / "webapp" / "main.js").read_text()

    assert "this.loopLoaded = false;" in main_js
    assert 'this.mode === "loop" && !this.loopLoaded' in main_js
    assert "this.worker.postMessage({ type: \"play\" });" in main_js
