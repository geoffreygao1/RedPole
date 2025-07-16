#include <Arduino.h>
#include "camera_handler.h"
#include "touch_handler.h"

// Touch + LED GPIO
#define TOUCH_PIN T1       // GPIO1
#define OUTPUT_PIN 6       // GPIO6
#define LED_PIN LED_BUILTIN
#define THRESHOLD_MIN 46700

bool lastOutputState = false;

TouchHandler touchHandler(TOUCH_PIN, OUTPUT_PIN, LED_PIN, THRESHOLD_MIN);

void sendPhotoBase64();

void setup() {
  Serial.begin(115200);
  while (!Serial);
  delay(1000);
  initCamera();
}

void loop() {
  touchHandler.update();

  if (touchHandler.isOutputActive()) {
    if (!lastOutputState){
      delay(500); 
      capturePhotoToRAM();
      sendPhotoBase64();
      lastOutputState = true;
    }
  } else {
    lastOutputState = false;
  }

  delay(10);
}
