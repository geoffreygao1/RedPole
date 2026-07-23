import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_loop_mode_cannot_post_play_before_loop_is_loaded():
    main_js = (ROOT / "webapp" / "main.js").read_text()

    assert "this.loopLoaded = false;" in main_js
    assert 'if (this.mode === "synth")' in main_js
    assert "if (!this.loopLoaded)" in main_js
    assert 'this.worker.postMessage({ type: "play", mode: this.mode });' in main_js


def test_play_message_carries_mode_and_worker_applies_it_before_unpausing():
    main_js = (ROOT / "webapp" / "main.js").read_text()
    worker_js = (ROOT / "webapp" / "worker.js").read_text()

    assert 'this.worker.postMessage({ type: "play", mode: this.mode });' in main_js
    play_branch = worker_js[
        worker_js.index('} else if (msg.type === "play")') :
        worker_js.index('} else if (msg.type === "pause")')
    ]
    assert "engine.ensure_mode" in play_branch
    assert play_branch.index("engine.ensure_mode") < play_branch.index("paused = false")


def test_mode_control_is_a_pill_switch_and_synth_options_are_not_visible():
    index_html = (ROOT / "webapp" / "index.html").read_text()
    main_js = (ROOT / "webapp" / "main.js").read_text()
    style_css = (ROOT / "webapp" / "style.css").read_text()

    assert 'class="mode-switch"' in index_html
    assert 'class="mode-switch-thumb"' in index_html
    assert 'id="tone-mode-select"' not in index_html
    assert 'id="harmony-mode-select"' not in index_html
    assert "synth-options" not in index_html
    assert "setSynthOptions" not in main_js
    assert "synthOptionsEl" not in main_js
    assert ".synth-options" not in style_css
    assert ".mode-switch-thumb" in style_css
    assert ".mode-switch.synth .mode-switch-thumb" in style_css


def test_synth_mode_patch_labels_show_sound_bath_effects():
    main_js = (ROOT / "webapp" / "main.js").read_text()

    assert 'const LOOP_ROW_LABELS = ["microloop", "granules", "glitch", "multidelay", "shape"];' in main_js
    assert 'const SYNTH_ROW_LABELS = MODIFIER_ROWS;' in main_js
    assert 'const SYNTH_SOURCE_ROWS = ["pluck", "pad", "bloom"];' in main_js
    assert '"piano", "guitar", "tapeguitar", "tapebell", "casio"' in main_js
    assert '"strings", "flute", "clarinet", "casio", "piano"' in main_js
    assert '"strings", "flute", "clarinet", "guitar", "tapebell"' in main_js
    assert "this.rowLabels()" in main_js
    assert 'this.mode === "synth" ? SYNTH_ROW_LABELS : LOOP_ROW_LABELS' in main_js
    assert "this.outputCellLabel(row, col)" in main_js


def test_synth_wash_controls_default_to_seventy_percent():
    index_html = (ROOT / "webapp" / "index.html").read_text()

    assert '<input id="reverb-slider" type="range" min="0" max="1.5" step="0.01" value="1.05" />' in index_html
    assert '<input id="delay-slider" type="range" min="0" max="1" step="0.01" value="0.7" />' in index_html


def test_pyodide_worker_loads_synth_bath_processor_before_web_engine():
    worker_js = (ROOT / "webapp" / "worker.js").read_text()

    assert '"synth_bath_processor.py"' in worker_js
    assert worker_js.index('"synth_bath_processor.py"') < worker_js.index('"web_engine.py"')


def test_deployed_worker_uses_webapp_audio_dependency_copies():
    worker_js = (ROOT / "webapp" / "worker.js").read_text()
    names = [
        "modulation.py",
        "layers.py",
        "tape_modulator.py",
        "microcosm_processor.py",
        "reverb.py",
        "wet_bus.py",
        "crowd.py",
        "spectral_stretch.py",
        "synth_source.py",
        "synth_bath_processor.py",
        "web_engine.py",
    ]

    assert "`audio/${name}?v=${PYTHON_SOURCE_VERSION}`" in worker_js
    assert "`../audio_prototype/${name}?v=${PYTHON_SOURCE_VERSION}`" in worker_js
    for name in names:
        deployed_copy = ROOT / "webapp" / "audio" / name
        source = ROOT / "audio_prototype" / name
        assert deployed_copy.exists(), name
        assert deployed_copy.read_text() == source.read_text()


def test_deployed_assets_are_cache_busted_from_index_to_worker():
    index_html = (ROOT / "webapp" / "index.html").read_text()
    main_js = (ROOT / "webapp" / "main.js").read_text()

    assert 'src="main.js?v=' in index_html
    assert "const APP_ASSET_VERSION = Date.now().toString();" in main_js
    assert 'new Worker(`worker.js?v=${APP_ASSET_VERSION}`)' in main_js
    assert 'addModule(`worklet.js?v=${APP_ASSET_VERSION}`)' in main_js


def test_pyodide_worker_cache_busts_python_sources():
    worker_js = (ROOT / "webapp" / "worker.js").read_text()

    assert "PYTHON_SOURCE_VERSION" in worker_js
    assert "?v=${PYTHON_SOURCE_VERSION}" in worker_js
    assert 'cache: "no-store"' in worker_js


def test_pyodide_worker_uses_larger_blocks_for_python_dsp_headroom():
    worker_js = (ROOT / "webapp" / "worker.js").read_text()

    assert "const BLOCK_FRAMES = 8192;" in worker_js
    assert "const HIGH_WATERMARK_SECONDS = 0.75;" in worker_js


def test_sources_are_left_of_patch_bay_and_drag_routed_explicitly():
    index_html = (ROOT / "webapp" / "index.html").read_text()
    main_js = (ROOT / "webapp" / "main.js").read_text()
    worker_js = (ROOT / "webapp" / "worker.js").read_text()

    assert index_html.index('id="sources"') < index_html.index('id="patch-bay"')
    assert 'source.slot = slot;' in main_js
    assert 'source.x = position.x;' in main_js
    assert 'source.y = position.y;' in main_js
    assert "assignSourceToOutput" in main_js
    assert "routeSourceToEffect" in main_js
    assert "onSourceListDragStart" in main_js
    assert "onSourceListClick" in main_js
    assert "selectedSourceId" in main_js
    assert 'id="auto-assign-sources"' in index_html
    assert "autoAssignSourcesEl" in main_js
    assert "nextAvailableOutputSlot" in main_js
    assert "this.assignSourceToOutput(sourceId, slot)" in main_js
    assert 'Click a source, then an output' in index_html
    assert 'Drag or click to assign' not in main_js
    assert 'sourceShortLabel(source)' in main_js
    assert 'li.draggable = true;' in main_js
    assert 'source.row = null;' in main_js
    assert 'source.col = null;' in main_js
    assert 'source.slot = null;' in main_js
    assert 'type: "connect_source",' in main_js
    assert "outputSlot: source.slot" in main_js
    assert "output_slot=" in worker_js
    assert "this.assignSourceToOutput(this.dragSourceId, slot)" in main_js

    finish_pending = main_js[
        main_js.index("finishPendingSource(sourceId)") :
        main_js.index("cellAt(x, y)")
    ]
    assert 'type: "connect_source"' not in finish_pending
    assert "nextSourceSlot" not in main_js

    assign_body = main_js[
        main_js.index("assignSourceToOutput(sourceId, slot)") :
        main_js.index("routeSourceToEffect(sourceId, cell)")
    ]
    assert 'type: "connect_source"' not in assign_body

    style_css = (ROOT / "webapp" / "style.css").read_text()
    assert "#app" in style_css
    assert "grid-template-columns: 260px 176px 830px;" in style_css
    assert "flex-wrap" not in style_css
    assert "#sources" in style_css
    assert "width: 176px;" in style_css
    assert "#patch-bay" in style_css
    assert "width: 830px;" in style_css
    assert "white-space: nowrap;" in style_css
    assert 'removeButton.textContent = "\\u00d7";' in main_js
    assert 'removeButton.className = "icon-button";' in main_js
    assert 'removeButton.setAttribute("aria-label", "Remove source");' in main_js
    assert 'removeButton.textContent = "Remove";' not in main_js
    assert ".icon-button" in style_css
    assert ".icon-button::before" in style_css
    assert "flex: 0 0 22px;" in style_css


def test_scan_controls_have_polished_actions_and_inline_color_preview():
    index_html = (ROOT / "webapp" / "index.html").read_text()
    style_css = (ROOT / "webapp" / "style.css").read_text()

    assert 'class="control-row transport-row"' in index_html
    assert 'id="play-pause-button" class="button-primary transport-button"' in index_html
    assert 'id="random-button" class="button-secondary"' in index_html
    assert 'id="send-button" class="button-primary"' in index_html
    assert 'class="control-row scan-parameter-row"' in index_html
    assert index_html.index('id="bpm-input"') < index_html.index('id="scan-color-preview"')

    assert ".button-primary" in style_css
    assert ".button-secondary" in style_css
    assert ".transport-button" in style_css
    assert ".scan-parameter-row" in style_css
    assert "#scan-color-preview" in style_css
    assert "width: 42px;" in style_css
    assert "height: 30px;" in style_css


def test_web_synth_loads_local_samples_without_a_committed_manifest():
    index_html = (ROOT / "webapp" / "index.html").read_text()
    main_js = (ROOT / "webapp" / "main.js").read_text()
    worker_js = (ROOT / "webapp" / "worker.js").read_text()
    gitignore = (ROOT / ".gitignore").read_text()

    assert "SYNTH_SAMPLE_MANIFEST" not in main_js
    assert 'id="load-samples-button"' in index_html
    assert 'id="load-samples-file"' in index_html
    assert "multiple" in index_html
    assert "loadSynthSamples" in main_js
    assert 'type: "load_synth_sample"' in main_js
    assert 'msg.type === "load_synth_sample"' in worker_js
    assert "webapp/assets/samples/" in gitignore


def test_webapp_js_passes_node_syntax_check():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    files = sorted((ROOT / "webapp").glob("*.js"))
    files.extend(sorted((ROOT / "webapp" / "generative").glob("*.js")))
    for path in files:
        result = subprocess.run(
            [node, "--check", str(path.relative_to(ROOT))],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout


def test_webapp_generative_suite_passes_node_test():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    result = subprocess.run(
        [node, "--test", "webapp/generative/"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
