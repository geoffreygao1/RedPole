#include "touch_handler.h"

TouchHandler::TouchHandler(int touchPin, int outputPin, int ledPin, int thresholdMin)
    : _touchPin(touchPin), _outputPin(outputPin), _ledPin(ledPin),
      _thresholdMin(thresholdMin)
{
    pinMode(_outputPin, OUTPUT);
    pinMode(_ledPin, OUTPUT);
    digitalWrite(_outputPin, LOW);
    digitalWrite(_ledPin, HIGH);
}

void TouchHandler::update() {
    int touchVal = touchRead(_touchPin);
    // delay(100);
    // Serial.printf("Touch value: %d\n", touchVal);

    if ((touchVal >= _thresholdMin) && !_outputActive)
    {
        activateOutput();
    }

    if (_outputActive && (touchVal < _thresholdMin))
    {
        deactivateOutput();
    }
}

void TouchHandler::activateOutput() {
    _outputActive = true;
    digitalWrite(_ledPin, LOW);
    digitalWrite(_outputPin, HIGH);
    // Serial.println("TOUCH");
}

void TouchHandler::deactivateOutput() {
    _outputActive = false;
    digitalWrite(_outputPin, LOW);
    digitalWrite(_ledPin, HIGH);
    // Serial.println("Released");
}

bool TouchHandler::isOutputActive() const {
    return _outputActive;
}
