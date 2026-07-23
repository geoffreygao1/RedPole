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


def test_sampler_macro_soundbath_grid_config_is_5x5_and_sample_only():
    config_js = (ROOT / "webapp" / "soundbath_config.js").read_text()

    assert 'const SOURCE_ROWS = ["pluck", "pad", "bloom", "bell", "drone"];' in config_js
    assert 'const MACRO_ROWS = ["veil", "shimmer", "flutter", "scatter", "space"];' in config_js
    assert '"piano", "guitar", "tapeguitar", "tapebell", "casio"' in config_js
    assert '"strings", "flute", "clarinet", "casio", "piano"' in config_js
    assert '"strings", "flute", "clarinet", "tapebell", "guitar"' in config_js
    assert '"tapebell", "casio", "piano", "guitar", "flute"' in config_js
    assert '"strings", "casio", "flute", "clarinet", "tapeguitar"' in config_js
    assert "export function sourceForSlot" in config_js
    assert "export function macroPresetId" in config_js


def test_synth_mode_routes_patch_cables_to_macro_grid():
    main_js = (ROOT / "webapp" / "main.js").read_text()

    assert 'routeSourceToMacro(sourceId, cell)' in main_js
    assert 'routeSourceToTrigger' not in main_js
    assert 'TRIGGER_ROWS' not in main_js
    assert 'TRIGGER_COLS' not in main_js
    assert 'triggerPresetId' not in main_js
    assert 'const SYNTH_ROW_LABELS = MACRO_ROWS;' in main_js
    assert 'const SYNTH_SOURCE_ROWS = SOURCE_ROWS;' in main_js
    assert 'const SYNTH_SOURCE_INSTRUMENTS = SOURCE_GRID;' in main_js
    assert 'this.scheduler?.setVoiceMacro(sourceId, macroId);' in main_js


def test_synth_mode_has_global_transpose_control():
    index_html = (ROOT / "webapp" / "index.html").read_text()
    main_js = (ROOT / "webapp" / "main.js").read_text()

    assert 'id="transpose-slider"' in index_html
    assert 'this.transposeSlider = document.getElementById("transpose-slider");' in main_js
    assert 'this.synthEngine.setTranspose(parseFloat(this.transposeSlider.value))' in main_js
    assert 'this.synthEngine?.setTranspose(parseFloat(e.target.value));' in main_js


def test_synth_patch_controls_are_midi_style_knobs_with_mood_palette():
    index_html = (ROOT / "webapp" / "index.html").read_text()
    main_js = (ROOT / "webapp" / "main.js").read_text()
    style_css = (ROOT / "webapp" / "style.css").read_text()

    assert 'class="patch-controls"' in index_html
    assert 'class="patch-control knob-control"' in index_html
    assert 'id="mood-select"' in index_html
    assert '<option value="optimistic">Optimistic</option>' in index_html
    assert '<option value="happy">Happy</option>' in index_html
    assert '<option value="mysterious">Mysterious</option>' in index_html
    assert '<option value="melancholy">Melancholy</option>' in index_html
    assert "this.moodSelect = document.getElementById(\"mood-select\");" in main_js
    assert "this.scheduler.setMood(this.moodSelect.value);" in main_js
    assert "this.scheduler?.setMood(e.target.value);" in main_js
    assert "syncKnobControl" in main_js
    assert ".knob-control" in style_css
    assert "conic-gradient" in style_css
    assert "opacity: 0;" in style_css
    assert ".knob-control::before" in style_css
    assert ".knob-control input[type=\"range\"] {" in style_css


def test_patch_bay_arrays_and_knobs_have_balanced_layout():
    index_html = (ROOT / "webapp" / "index.html").read_text()
    main_js = (ROOT / "webapp" / "main.js").read_text()
    style_css = (ROOT / "webapp" / "style.css").read_text()

    assert "const PATCH_CELL = 50;" in main_js
    assert "const OUTPUT_GRID_X = 54;" in main_js
    assert "const PATCH_GRID_X = 362;" in main_js
    assert 'ctx.fillText("sources", OUTPUT_GRID_X, OUTPUT_GRID_Y - 18);' in main_js
    assert 'ctx.fillText("effects", PATCH_GRID_X + PATCH_GRID_COLS * PATCH_CELL + 16, PATCH_GRID_Y - 18);' in main_js
    assert 'href="style.css?v=20260723-compact-patch-layout"' in index_html
    assert 'src="main.js?v=20260723-compact-patch-layout"' in index_html
    assert '<canvas id="picker" width="180" height="96"></canvas>' in index_html
    assert '<canvas id="patch-canvas" width="740" height="330"></canvas>' in index_html
    assert "grid-template-columns: repeat(6, minmax(64px, 1fr));" in style_css
    assert "justify-items: center;" in style_css
    assert "grid-template-columns: 220px 176px 778px;" in style_css
    assert "#scan-input {\n  width: 220px;" in style_css
    assert "#patch-bay {\n  width: 778px;" in style_css
    assert "transform: rotate(var(--knob-angle))" not in style_css


def test_effect_row_labels_are_drawn_on_right_side_of_effect_matrix():
    main_js = (ROOT / "webapp" / "main.js").read_text()

    start = main_js.index("for (let row = 0; row < PATCH_GRID_ROWS; row++)", main_js.index("drawPatchBay()"))
    effects_loop = main_js[
        main_js.index("for (let row = 0; row < PATCH_GRID_ROWS; row++)", start + 1) :
        main_js.index("for (const [, source] of this.sources)", start)
    ]
    assert "ctx.textAlign = \"left\";" in effects_loop
    assert "PATCH_GRID_X + PATCH_GRID_COLS * PATCH_CELL + 10" in effects_loop
    assert "PATCH_GRID_X - 12" not in effects_loop


def test_synth_output_jacks_use_roman_column_labels_not_instrument_names():
    main_js = (ROOT / "webapp" / "main.js").read_text()

    start = main_js.index("\n  outputCellLabel(row, col)")
    output_label_body = main_js[
        start :
        main_js.index("\n  drawPatchBay()", start)
    ]
    assert 'if (this.mode === "synth") return MACRO_COLS[col] ?? "";' in output_label_body
    assert "SYNTH_SOURCE_INSTRUMENTS" not in output_label_body


def test_reverb_high_end_is_extra_washed():
    tone_engine_js = (ROOT / "webapp" / "tone_engine.js").read_text()

    assert "this.reverb.decay = 14;" in tone_engine_js
    assert "const shaped = amount * amount;" in tone_engine_js
    assert "rampParam(this.reverb.wet, clamp(shaped * 1.25, 0, 1), 0.08);" in tone_engine_js
    assert "rampParam(this.delay.feedback, clamp(0.72 + shaped * 0.18, 0, 0.92), 0.08);" in tone_engine_js


def test_tone_buffers_uses_clickbath_base_url_for_sample_loading():
    tone_engine_js = (ROOT / "webapp" / "tone_engine.js").read_text()

    assert "new this.Tone.Buffers({ urls, baseUrl: CLICKBATH_BASE_URL })" in tone_engine_js
    assert "new this.Tone.Buffers(urls, { baseUrl: CLICKBATH_BASE_URL })" not in tone_engine_js


def test_scan_fingerprint_module_path_avoids_privacy_extension_blocking():
    main_js = (ROOT / "webapp" / "main.js").read_text()

    assert 'from "./generative/scan-profile.js' in main_js
    assert "generative/fingerprint.js" not in main_js


def test_mode_switch_pauses_loop_and_ignores_stale_source_replies():
    main_js = (ROOT / "webapp" / "main.js").read_text()

    set_mode_body = main_js[
        main_js.index("async setMode(mode)") :
        main_js.index("async onTogglePlay()")
    ]
    assert 'this.worker?.postMessage({ type: "pause" });' in set_mode_body
    assert 'if (this.audioContext?.state === "running") await this.audioContext.suspend();' in set_mode_body
    assert 'this.playPauseButton.textContent = "Play";' in set_mode_body

    finish_pending_body = main_js[
        main_js.index("finishPendingSource(sourceId)") :
        main_js.index("nextAvailableOutputSlot()")
    ]
    assert "const pending = this._pendingSources.shift();" in finish_pending_body
    assert "if (!pending) return;" in finish_pending_body


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
    assert 'href="style.css?v=' in index_html
    assert 'from "./scheduler.js?v=' in main_js
    assert 'from "./tone_engine.js?v=' in main_js
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
    assert "routeSourceToMacro" in main_js
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
        main_js.index("routeSourceToMacro(sourceId, cell)")
    ]
    assert 'type: "connect_source"' not in assign_body

    style_css = (ROOT / "webapp" / "style.css").read_text()
    assert "#app" in style_css
    assert "grid-template-columns: 220px 176px 778px;" in style_css
    assert "flex-wrap" not in style_css
    assert "#sources" in style_css
    assert "width: 176px;" in style_css
    assert "#patch-bay" in style_css
    assert "width: 778px;" in style_css
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
    assert "width: 34px;" in style_css
    assert "height: 24px;" in style_css


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
