#pragma once

#include <Arduino.h>

class TouchHandler {
public:
    TouchHandler(int touchPin, int outputPin, int ledPin, int thresholdMin);

    void update();
    bool isOutputActive() const;

private:
    int _touchPin, _outputPin, _ledPin;
    int _thresholdMin, _thresholdMax;

    bool _outputActive = false;

    void activateOutput();
    void deactivateOutput();
};