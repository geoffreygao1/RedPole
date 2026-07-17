#include <Arduino.h>
#include <FastLED.h>
#include "patch_logic.h"

// ---- hardware config ------------------------------------------------------
#define ACTIVE_JACKS 1        // bump to 4 when jacks 1-3 are wired
#define PRESENT_LEVEL LOW     // tip switch pulls the divider low when a plug is inserted (verified on hardware)
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
  if (state.hasStaged)
    Serial.printf("staged: #%02X%02X%02X\n", state.staged.r, state.staged.g, state.staged.b);
  else
    Serial.println("staged: none");
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
  if (strcmp(line, "random") == 0) {
    // Random hue at full saturation/value so the color is always vivid.
    CRGB rgb = CHSV(esp_random() & 0xFF, 255, 255);
    c = Color{rgb.r, rgb.g, rgb.b};
    Serial.printf("random color: #%02X%02X%02X\n", c.r, c.g, c.b);
    PatchEvent e = stageColor(state, c);
    logEvent(e);
    if (e.type == EV_RETRO_COLORED) renderJack(e.jackA);
    return;
  }
  if (parseHex(line, c) || parseCsv(line, c)) {
    PatchEvent e = stageColor(state, c);
    logEvent(e);
    if (e.type == EV_RETRO_COLORED) renderJack(e.jackA);
    return;
  }
  Serial.printf("unrecognized: '%s' (use #RRGGBB, R,G,B, random, status, off)\n", line);
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

  // FastLED needs the pin as a template constant; add one line per wired jack.
  FastLED.addLeds<PL9823, 9>(&leds[0], 1);  // jack 0, DIN on GPIO9 (D10)
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

  Serial.println("patch_prototype ready. commands: #RRGGBB | R,G,B | random | status | off");
}

void loop() {
  pollSerial();
  pollJacks();
  delay(2);
}
