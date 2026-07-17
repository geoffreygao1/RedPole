# Patch Prototype LED Cable Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PlatformIO firmware for a XIAO ESP32S3 that stages a color via serial and lights PL9823 LEDs in TRS patch cables, pairing the two ends of each cable via jack presence detection.

**Architecture:** A pure-logic core (`patch_logic.h/.cpp`, no Arduino dependencies) holds the `Jack` array, pending FIFO, and staged color, exposing `onInsert`/`onRemove`/`stageColor` transitions. `main.cpp` is a thin Arduino shell: debounced GPIO polling, FastLED output, and serial line parsing. Logic is host-testable with plain C++ asserts via PlatformIO's native test runner.

**Tech Stack:** PlatformIO, Arduino framework (espressif32), FastLED (PL9823 chipset), Unity test framework (bundled with PlatformIO) for native logic tests.

## Global Constraints

- Board: `seeed_xiao_esp32s3`, framework `arduino`, `monitor_speed = 115200`.
- Project root: `patch_prototype/` — a self-contained PlatformIO project (own `platformio.ini`), sibling of the repo's root firmware project.
- Pins (phase 1, jack 0 only): LED DIN = GPIO9 (D10), presence detect = GPIO8 (D9), configured `INPUT` (external 4.7k/4.7k divider sets levels).
- `NUM_JACKS = 4`, `ACTIVE_JACKS = 1`; presence polarity behind a `PRESENT_LEVEL` define defaulting to `HIGH`.
- Serial commands: `#RRGGBB`, `R,G,B`, `status`, `off` — newline-terminated, no jack-index addressing.
- Staged color is consumed only by a new-cable insertion (pending queue empty). Pairing with a pending jack copies the cable's color and leaves the staged color untouched.
- No color staged + new-cable insertion → LED stays dark, jack still becomes pending; a later color command applies retroactively to a colorless pending jack.
- Logic core (`patch_logic.*`) must not include any Arduino header.

---

### Task 1: Project scaffold + pure pairing/staging logic (TDD, native tests)

**Files:**
- Create: `patch_prototype/platformio.ini`
- Create: `patch_prototype/src/patch_logic.h`
- Create: `patch_prototype/src/patch_logic.cpp`
- Test: `patch_prototype/test/test_logic/test_patch_logic.cpp`

**Interfaces:**
- Produces (used by Task 2's `main.cpp`):
  - `struct Color { uint8_t r, g, b; };`
  - `struct Jack { bool present; int8_t pairedWith; Color color; bool hasColor; };`
  - `struct PatchState { Jack jacks[NUM_JACKS]; int8_t pendingQueue[NUM_JACKS]; uint8_t pendingCount; Color staged; bool hasStaged; };`
  - `void patchInit(PatchState& s);`
  - `PatchEvent stageColor(PatchState& s, Color c);` — stages; retroactively colors the oldest colorless pending jack if one exists
  - `PatchEvent onInsert(PatchState& s, uint8_t jack);`
  - `PatchEvent onRemove(PatchState& s, uint8_t jack);`
  - `void clearStaged(PatchState& s);`
  - `PatchEvent` = `struct { EventType type; int8_t jackA, jackB; }` with `enum EventType { EV_NONE, EV_STAGED, EV_RETRO_COLORED, EV_NEW_CABLE, EV_NEW_CABLE_DARK, EV_PAIRED, EV_UNPAIRED, EV_PENDING_REMOVED };` — the shell uses this to log and to know which LEDs to re-render.

- [ ] **Step 1: Create `patch_prototype/platformio.ini`**

```ini
[env:seeed_xiao_esp32s3]
platform = espressif32
board = seeed_xiao_esp32s3
framework = arduino
monitor_speed = 115200
lib_deps =
    fastled/FastLED@^3.7.0

[env:native]
platform = native
build_flags = -std=c++11
```

- [ ] **Step 2: Write `patch_logic.h`**

```cpp
#pragma once
#include <stdint.h>

#define NUM_JACKS 4

struct Color { uint8_t r, g, b; };

struct Jack {
  bool   present;
  int8_t pairedWith;   // partner index or -1
  Color  color;
  bool   hasColor;
};

enum EventType {
  EV_NONE,
  EV_STAGED,           // color stored for next new cable
  EV_RETRO_COLORED,    // staged color applied to colorless pending jack (jackA)
  EV_NEW_CABLE,        // jackA inserted, took staged color
  EV_NEW_CABLE_DARK,   // jackA inserted, nothing staged, stays dark
  EV_PAIRED,           // jackA inserted, paired with jackB, copied its color
  EV_UNPAIRED,         // jackA removed, jackB back to pending
  EV_PENDING_REMOVED   // jackA removed while pending
};

struct PatchEvent { EventType type; int8_t jackA, jackB; };

struct PatchState {
  Jack    jacks[NUM_JACKS];
  int8_t  pendingQueue[NUM_JACKS];
  uint8_t pendingCount;
  Color   staged;
  bool    hasStaged;
};

void       patchInit(PatchState& s);
PatchEvent stageColor(PatchState& s, Color c);
PatchEvent onInsert(PatchState& s, uint8_t jack);
PatchEvent onRemove(PatchState& s, uint8_t jack);
void       clearStaged(PatchState& s);
```

- [ ] **Step 3: Write failing tests in `test/test_logic/test_patch_logic.cpp`**

Cover, using Unity (`#include <unity.h>`), the full spec walkthrough:

```cpp
#include <unity.h>
#include "patch_logic.h"

static PatchState s;
void setUp() { patchInit(s); }
void tearDown() {}

static Color RED()  { Color c{255,0,0}; return c; }
static Color BLUE() { Color c{0,0,255}; return c; }

void test_init_state() {
  TEST_ASSERT_EQUAL(0, s.pendingCount);
  TEST_ASSERT_FALSE(s.hasStaged);
  for (int i = 0; i < NUM_JACKS; i++) {
    TEST_ASSERT_FALSE(s.jacks[i].present);
    TEST_ASSERT_EQUAL(-1, s.jacks[i].pairedWith);
    TEST_ASSERT_FALSE(s.jacks[i].hasColor);
  }
}

void test_stage_then_insert_lights_new_cable() {
  stageColor(s, RED());
  PatchEvent e = onInsert(s, 0);
  TEST_ASSERT_EQUAL(EV_NEW_CABLE, e.type);
  TEST_ASSERT_EQUAL(0, e.jackA);
  TEST_ASSERT_TRUE(s.jacks[0].hasColor);
  TEST_ASSERT_EQUAL(255, s.jacks[0].color.r);
  TEST_ASSERT_FALSE(s.hasStaged);          // consumed
  TEST_ASSERT_EQUAL(1, s.pendingCount);
}

void test_insert_without_staged_stays_dark_but_pending() {
  PatchEvent e = onInsert(s, 0);
  TEST_ASSERT_EQUAL(EV_NEW_CABLE_DARK, e.type);
  TEST_ASSERT_FALSE(s.jacks[0].hasColor);
  TEST_ASSERT_EQUAL(1, s.pendingCount);
}

void test_retroactive_color_on_colorless_pending() {
  onInsert(s, 0);                          // dark pending
  PatchEvent e = stageColor(s, RED());
  TEST_ASSERT_EQUAL(EV_RETRO_COLORED, e.type);
  TEST_ASSERT_EQUAL(0, e.jackA);
  TEST_ASSERT_TRUE(s.jacks[0].hasColor);
  TEST_ASSERT_FALSE(s.hasStaged);          // consumed by retro-apply
}

void test_second_insert_pairs_and_copies_color() {
  stageColor(s, RED());
  onInsert(s, 0);
  PatchEvent e = onInsert(s, 2);
  TEST_ASSERT_EQUAL(EV_PAIRED, e.type);
  TEST_ASSERT_EQUAL(2, e.jackA);
  TEST_ASSERT_EQUAL(0, e.jackB);
  TEST_ASSERT_EQUAL(0, s.jacks[2].pairedWith);
  TEST_ASSERT_EQUAL(255, s.jacks[2].color.r);
  TEST_ASSERT_EQUAL(0, s.pendingCount);
}

void test_pairing_does_not_consume_staged() {
  stageColor(s, RED());
  onInsert(s, 0);                          // consumes red
  onInsert(s, 2);                          // pairs
  stageColor(s, BLUE());                   // staged for next cable
  PatchEvent e = onInsert(s, 1);
  TEST_ASSERT_EQUAL(EV_NEW_CABLE, e.type);
  TEST_ASSERT_EQUAL(255, s.jacks[1].color.b);
}

void test_unplug_one_end_keeps_other_glowing_pending() {
  stageColor(s, RED());
  onInsert(s, 0);
  onInsert(s, 2);
  PatchEvent e = onRemove(s, 2);
  TEST_ASSERT_EQUAL(EV_UNPAIRED, e.type);
  TEST_ASSERT_EQUAL(2, e.jackA);
  TEST_ASSERT_EQUAL(0, e.jackB);
  TEST_ASSERT_EQUAL(-1, s.jacks[0].pairedWith);
  TEST_ASSERT_TRUE(s.jacks[0].hasColor);   // still glowing
  TEST_ASSERT_EQUAL(1, s.pendingCount);    // 0 pending again
}

void test_replug_loose_end_elsewhere_copies_cable_color() {
  stageColor(s, RED());
  onInsert(s, 0);
  onInsert(s, 2);
  onRemove(s, 2);
  PatchEvent e = onInsert(s, 1);           // ID3 -> ID2 move
  TEST_ASSERT_EQUAL(EV_PAIRED, e.type);
  TEST_ASSERT_EQUAL(1, e.jackA);
  TEST_ASSERT_EQUAL(0, e.jackB);
  TEST_ASSERT_EQUAL(255, s.jacks[1].color.r);
}

void test_remove_pending_jack_drops_from_queue() {
  stageColor(s, RED());
  onInsert(s, 0);
  PatchEvent e = onRemove(s, 0);
  TEST_ASSERT_EQUAL(EV_PENDING_REMOVED, e.type);
  TEST_ASSERT_EQUAL(0, s.pendingCount);
  TEST_ASSERT_TRUE(s.jacks[0].hasColor);   // color remembered
}

void test_fifo_pairs_oldest_pending_first() {
  stageColor(s, RED());
  onInsert(s, 0);                          // pending: [0]
  onInsert(s, 1);                          // pairs with 0 -> queue empty
  stageColor(s, BLUE());
  onInsert(s, 2);                          // new cable, pending: [2]
  PatchEvent e = onInsert(s, 3);
  TEST_ASSERT_EQUAL(EV_PAIRED, e.type);
  TEST_ASSERT_EQUAL(2, e.jackB);
}

void test_clear_staged() {
  stageColor(s, RED());
  clearStaged(s);
  PatchEvent e = onInsert(s, 0);
  TEST_ASSERT_EQUAL(EV_NEW_CABLE_DARK, e.type);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_init_state);
  RUN_TEST(test_stage_then_insert_lights_new_cable);
  RUN_TEST(test_insert_without_staged_stays_dark_but_pending);
  RUN_TEST(test_retroactive_color_on_colorless_pending);
  RUN_TEST(test_second_insert_pairs_and_copies_color);
  RUN_TEST(test_pairing_does_not_consume_staged);
  RUN_TEST(test_unplug_one_end_keeps_other_glowing_pending);
  RUN_TEST(test_replug_loose_end_elsewhere_copies_cable_color);
  RUN_TEST(test_remove_pending_jack_drops_from_queue);
  RUN_TEST(test_fifo_pairs_oldest_pending_first);
  RUN_TEST(test_clear_staged);
  return UNITY_END();
}
```

Note: PlatformIO's native test env compiles `src/` alongside tests, but `main.cpp` (added in Task 2) must be excluded from the native build — add to `[env:native]`: `build_src_filter = +<*> -<main.cpp>`. Include that line now so Task 2 doesn't break tests.

- [ ] **Step 4: Run tests, verify they fail**

Run: `pio test -e native -d patch_prototype`
Expected: link/compile failure — `patch_logic.cpp` functions undefined.

- [ ] **Step 5: Implement `patch_logic.cpp`**

```cpp
#include "patch_logic.h"

static void pendingPush(PatchState& s, int8_t j) {
  s.pendingQueue[s.pendingCount++] = j;
}

static int8_t pendingPopOldest(PatchState& s) {
  int8_t j = s.pendingQueue[0];
  for (uint8_t i = 1; i < s.pendingCount; i++)
    s.pendingQueue[i - 1] = s.pendingQueue[i];
  s.pendingCount--;
  return j;
}

static void pendingRemove(PatchState& s, int8_t j) {
  uint8_t w = 0;
  for (uint8_t i = 0; i < s.pendingCount; i++)
    if (s.pendingQueue[i] != j) s.pendingQueue[w++] = s.pendingQueue[i];
  s.pendingCount = w;
}

void patchInit(PatchState& s) {
  for (int i = 0; i < NUM_JACKS; i++) {
    s.jacks[i].present = false;
    s.jacks[i].pairedWith = -1;
    s.jacks[i].color = Color{0, 0, 0};
    s.jacks[i].hasColor = false;
  }
  s.pendingCount = 0;
  s.hasStaged = false;
  s.staged = Color{0, 0, 0};
}

PatchEvent stageColor(PatchState& s, Color c) {
  // Retroactively color the oldest colorless pending jack, if any.
  for (uint8_t i = 0; i < s.pendingCount; i++) {
    int8_t j = s.pendingQueue[i];
    if (!s.jacks[j].hasColor) {
      s.jacks[j].color = c;
      s.jacks[j].hasColor = true;
      return PatchEvent{EV_RETRO_COLORED, j, -1};
    }
  }
  s.staged = c;
  s.hasStaged = true;
  return PatchEvent{EV_STAGED, -1, -1};
}

void clearStaged(PatchState& s) { s.hasStaged = false; }

PatchEvent onInsert(PatchState& s, uint8_t jack) {
  s.jacks[jack].present = true;
  if (s.pendingCount > 0) {
    int8_t p = pendingPopOldest(s);
    s.jacks[jack].pairedWith = p;
    s.jacks[p].pairedWith = jack;
    s.jacks[jack].color = s.jacks[p].color;
    s.jacks[jack].hasColor = s.jacks[p].hasColor;
    return PatchEvent{EV_PAIRED, (int8_t)jack, p};
  }
  pendingPush(s, jack);
  if (s.hasStaged) {
    s.jacks[jack].color = s.staged;
    s.jacks[jack].hasColor = true;
    s.hasStaged = false;
    return PatchEvent{EV_NEW_CABLE, (int8_t)jack, -1};
  }
  return PatchEvent{EV_NEW_CABLE_DARK, (int8_t)jack, -1};
}

PatchEvent onRemove(PatchState& s, uint8_t jack) {
  s.jacks[jack].present = false;
  int8_t p = s.jacks[jack].pairedWith;
  if (p >= 0) {
    s.jacks[jack].pairedWith = -1;
    s.jacks[p].pairedWith = -1;
    pendingPush(s, p);
    return PatchEvent{EV_UNPAIRED, (int8_t)jack, p};
  }
  pendingRemove(s, jack);
  return PatchEvent{EV_PENDING_REMOVED, (int8_t)jack, -1};
}
```

- [ ] **Step 6: Run tests, verify they pass**

Run: `pio test -e native -d patch_prototype`
Expected: `11 Tests 0 Failures 0 Ignored` — PASS

- [ ] **Step 7: Commit**

```bash
git add patch_prototype/platformio.ini patch_prototype/src/patch_logic.h patch_prototype/src/patch_logic.cpp patch_prototype/test/test_logic/test_patch_logic.cpp
git commit -m "feat: patch prototype pairing/staging logic with native tests"
```

---

### Task 2: Arduino shell — serial parsing, debounce, FastLED output

**Files:**
- Create: `patch_prototype/src/main.cpp`
- Modify: `patch_prototype/platformio.ini` (only if `build_src_filter` line was missed in Task 1)

**Interfaces:**
- Consumes: everything in `patch_logic.h` (Task 1). No new interfaces produced.

- [ ] **Step 1: Write `main.cpp`**

```cpp
#include <Arduino.h>
#include <FastLED.h>
#include "patch_logic.h"

// ---- hardware config ------------------------------------------------------
#define ACTIVE_JACKS 1        // bump to 4 when jacks 1-3 are wired
#define PRESENT_LEVEL HIGH    // flip if presence reads inverted at boot
#define DEBOUNCE_MS 30

// Per-jack pins. Only the first ACTIVE_JACKS entries are used.
static const uint8_t LED_PINS[NUM_JACKS]   = {9, 0, 0, 0};   // D10 = GPIO9
static const uint8_t SENSE_PINS[NUM_JACKS] = {8, 0, 0, 0};   // D9  = GPIO8

// ---- state ----------------------------------------------------------------
static PatchState state;
static CRGB leds[NUM_JACKS];  // one pixel per jack, each on its own pin

struct Debounce {
  bool stable;
  bool lastRaw;
  uint32_t lastChangeMs;
};
static Debounce debounce[NUM_JACKS];

static char lineBuf[32];
static uint8_t lineLen = 0;

// ---- rendering -------------------------------------------------------------
static void renderJack(uint8_t j) {
  bool lit = state.jacks[j].present && state.jacks[j].hasColor;
  Color c = state.jacks[j].color;
  leds[j] = lit ? CRGB(c.r, c.g, c.b) : CRGB::Black;
  FastLED.show();
}

// ---- logging ---------------------------------------------------------------
static void logEvent(const PatchEvent& e) {
  switch (e.type) {
    case EV_STAGED:
      Serial.println("color staged for next new cable");
      break;
    case EV_RETRO_COLORED:
      Serial.printf("jack %d (pending, colorless) colored retroactively\n", e.jackA);
      break;
    case EV_NEW_CABLE:
      Serial.printf("jack %d: new cable, staged color applied\n", e.jackA);
      break;
    case EV_NEW_CABLE_DARK:
      Serial.printf("jack %d: new cable, no color staged (dark)\n", e.jackA);
      break;
    case EV_PAIRED:
      Serial.printf("jack %d paired with jack %d, color copied\n", e.jackA, e.jackB);
      break;
    case EV_UNPAIRED:
      Serial.printf("jack %d removed; jack %d keeps color, pending\n", e.jackA, e.jackB);
      break;
    case EV_PENDING_REMOVED:
      Serial.printf("jack %d removed (was pending)\n", e.jackA);
      break;
    default: break;
  }
}

// ---- serial commands --------------------------------------------------------
static bool parseHex(const char* s, Color& out) {
  if (s[0] != '#' || strlen(s) != 7) return false;
  char* end;
  long v = strtol(s + 1, &end, 16);
  if (*end != '\0') return false;
  out = Color{(uint8_t)(v >> 16), (uint8_t)(v >> 8), (uint8_t)v};
  return true;
}

static bool parseCsv(const char* s, Color& out) {
  int r, g, b;
  if (sscanf(s, "%d,%d,%d", &r, &g, &b) != 3) return false;
  if (r < 0 || r > 255 || g < 0 || g > 255 || b < 0 || b > 255) return false;
  out = Color{(uint8_t)r, (uint8_t)g, (uint8_t)b};
  return true;
}

static void printStatus() {
  Serial.printf("staged: %s", state.hasStaged ? "" : "none\n");
  if (state.hasStaged)
    Serial.printf("#%02X%02X%02X\n", state.staged.r, state.staged.g, state.staged.b);
  for (uint8_t j = 0; j < ACTIVE_JACKS; j++) {
    const Jack& jk = state.jacks[j];
    Serial.printf("jack %d: %s paired=%d color=", j,
                  jk.present ? "IN " : "out", jk.pairedWith);
    if (jk.hasColor)
      Serial.printf("#%02X%02X%02X\n", jk.color.r, jk.color.g, jk.color.b);
    else
      Serial.println("none");
  }
  Serial.printf("pending queue (%d):", state.pendingCount);
  for (uint8_t i = 0; i < state.pendingCount; i++)
    Serial.printf(" %d", state.pendingQueue[i]);
  Serial.println();
}

static void handleLine(const char* line) {
  if (line[0] == '\0') return;
  if (strcmp(line, "status") == 0) { printStatus(); return; }
  if (strcmp(line, "off") == 0) {
    clearStaged(state);
    Serial.println("staged color cleared");
    return;
  }
  Color c;
  if (parseHex(line, c) || parseCsv(line, c)) {
    PatchEvent e = stageColor(state, c);
    logEvent(e);
    if (e.type == EV_RETRO_COLORED) renderJack(e.jackA);
    return;
  }
  Serial.printf("unrecognized: '%s' (use #RRGGBB, R,G,B, status, off)\n", line);
}

static void pollSerial() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      lineBuf[lineLen] = '\0';
      handleLine(lineBuf);
      lineLen = 0;
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = ch;
    }
  }
}

// ---- presence polling --------------------------------------------------------
static void pollJacks() {
  uint32_t now = millis();
  for (uint8_t j = 0; j < ACTIVE_JACKS; j++) {
    bool raw = digitalRead(SENSE_PINS[j]) == PRESENT_LEVEL;
    if (raw != debounce[j].lastRaw) {
      debounce[j].lastRaw = raw;
      debounce[j].lastChangeMs = now;
    }
    if (raw != debounce[j].stable && (now - debounce[j].lastChangeMs) >= DEBOUNCE_MS) {
      debounce[j].stable = raw;
      PatchEvent e = raw ? onInsert(state, j) : onRemove(state, j);
      logEvent(e);
      renderJack(j);
      if (e.type == EV_PAIRED || e.type == EV_UNPAIRED) renderJack(e.jackB);
    }
  }
}

// ---- setup / loop --------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(500);
  patchInit(state);

  FastLED.addLeds<PL9823, 9>(&leds[0], 1);  // jack 0, GPIO9 (template needs a constant)
  FastLED.clear(true);

  for (uint8_t j = 0; j < ACTIVE_JACKS; j++) {
    pinMode(SENSE_PINS[j], INPUT);
    bool raw = digitalRead(SENSE_PINS[j]) == PRESENT_LEVEL;
    debounce[j] = Debounce{raw, raw, 0};
    if (raw) {   // jack already inserted at boot
      PatchEvent e = onInsert(state, j);
      logEvent(e);
    }
    Serial.printf("jack %d sense raw=%d -> %s (PRESENT_LEVEL=%s)\n",
                  j, digitalRead(SENSE_PINS[j]), raw ? "present" : "absent",
                  PRESENT_LEVEL == HIGH ? "HIGH" : "LOW");
  }

  Serial.println("patch_prototype ready. commands: #RRGGBB | R,G,B | status | off");
}

void loop() {
  pollSerial();
  pollJacks();
  delay(2);
}
```

Note on FastLED: `addLeds<CHIPSET, PIN>` takes the pin as a template constant, so when jacks 1–3 are wired, add three more explicit `addLeds<PL9823, X>(&leds[n], 1)` lines — this is expected and documented by the comment.

- [ ] **Step 2: Verify the native tests still pass (main.cpp must be excluded)**

Run: `pio test -e native -d patch_prototype`
Expected: `11 Tests 0 Failures 0 Ignored` — if `main.cpp` breaks the native build, confirm `[env:native]` has `build_src_filter = +<*> -<main.cpp>`.

- [ ] **Step 3: Build for the target board**

Run: `pio run -e seeed_xiao_esp32s3 -d patch_prototype`
Expected: `SUCCESS` (FastLED downloads on first run).

- [ ] **Step 4: Commit**

```bash
git add patch_prototype/src/main.cpp patch_prototype/platformio.ini
git commit -m "feat: patch prototype serial shell with FastLED and presence detect"
```

---

### Task 3: Hardware smoke test (manual, user at the bench)

**Files:** none (verification only)

- [ ] **Step 1: Flash**

Run: `pio run -e seeed_xiao_esp32s3 -d patch_prototype -t upload`
Then: `pio device monitor -d patch_prototype`

- [ ] **Step 2: Verify presence polarity**

Boot banner shows `jack 0 sense raw=...`. Plug and unplug the TRS cable; confirm "jack 0: new cable..." / "jack 0 removed" logs match physical reality. If inverted, flip `PRESENT_LEVEL` to `LOW`, reflash, and note which polarity is correct in a code comment.

- [ ] **Step 3: Verify spec success criteria**

1. Send `#FF00A0`, insert plug → LED lights magenta.
2. Unplug, send `status` → color still remembered (`hasColor` shown), pending queue empty.
3. Unplug everything, insert with nothing staged → LED dark; then send `#00FF00` → LED turns green (retroactive coloring).
4. Confirm no insert/remove log chatter (debounce working).

- [ ] **Step 4: Commit any polarity/config fix**

```bash
git add patch_prototype/src/main.cpp
git commit -m "fix: confirm presence detect polarity on hardware"
```
