// src/camera_handler.cpp

#include <Arduino.h>
#include "camera_handler.h"
#include "esp_camera.h"
#include "base64.hpp"

uint8_t* jpegCopy = nullptr;
size_t jpegLen = 0;

void capturePhotoToRAM() {
    if (jpegCopy) {
        free(jpegCopy);
        jpegCopy = nullptr;
        jpegLen = 0;
    }

    // Discard the first frame
    camera_fb_t* temp = esp_camera_fb_get();
    if (temp) {
        esp_camera_fb_return(temp);
        delay(500);
    }

    // Use the second (fresh) frame
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("Failed to capture photo");
        return;
    }

    jpegLen = fb->len;
    jpegCopy = (uint8_t*)malloc(jpegLen);
    if (jpegCopy) {
        memcpy(jpegCopy, fb->buf, jpegLen);
    } else {
        Serial.println("Failed to allocate jpegCopy buffer");
    }

    esp_camera_fb_return(fb);
}


void sendPhotoBase64() {
    if (!jpegCopy || jpegLen == 0) {
        Serial.println("Error: No image in RAM");
        return;
    }

    unsigned int base64Len = encode_base64_length(jpegLen);
    unsigned char* base64Buf = (unsigned char*)malloc(base64Len + 1);
    if (!base64Buf) {
        Serial.println("Error: Couldn't allocate Base64 buffer");
        return;
    }

    encode_base64(jpegCopy, jpegLen, base64Buf);
    base64Buf[base64Len] = '\0';

    Serial.println("===IMAGE_START===");

    for (unsigned int i = 0; i < base64Len; i += 64) {
        unsigned int chunkLen = (base64Len - i < 64) ? (base64Len - i) : 64;
        char chunk[65]; 
        memcpy(chunk, &base64Buf[i], chunkLen);
        chunk[chunkLen] = '\0';
        Serial.println(chunk);  
    }
    
    Serial.println("===IMAGE_END===");

    free(base64Buf);
}


void initCamera() {
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer   = LEDC_TIMER_0;
    config.pin_d0 = 15; config.pin_d1 = 17; config.pin_d2 = 18; config.pin_d3 = 16;
    config.pin_d4 = 14; config.pin_d5 = 12; config.pin_d6 = 11; config.pin_d7 = 48;
    config.pin_xclk = 10;
    config.pin_pclk = 13;
    config.pin_vsync = 38;
    config.pin_href  = 47;
    config.pin_sccb_sda = 40;
    config.pin_sccb_scl = 39;
    config.pin_pwdn  = -1;
    config.pin_reset = -1;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;
    config.frame_size = FRAMESIZE_UXGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;

    if (esp_camera_init(&config) != ESP_OK) {
        Serial.println("Camera init failed!");
        return;
    }

    // Set camera sensor settings
    sensor_t* s = esp_camera_sensor_get();
    s->set_exposure_ctrl(s, 0);
    s->set_aec2(s, 0);
    s->set_ae_level(s, -2);
    s->set_aec_value(s, 50);
    s->set_gain_ctrl(s, 0);
    s->set_agc_gain(s, 5);
    s->set_brightness(s, -2);
    s->set_contrast(s, 0);
    s->set_saturation(s, 2);
    s->set_whitebal(s, 0);
    s->set_awb_gain(s, 0);
    s->set_bpc(s, 1);
    s->set_wpc(s, 1);
    s->set_lenc(s, 1);
    s->set_raw_gma(s, 1);
    s->set_hmirror(s, 0);
    s->set_vflip(s, 1);
}
