#ifndef CAMERA_HANDLER_H
#define CAMERA_HANDLER_H

#include <esp_http_server.h>

void initCamera();
void capturePhotoToRAM();
void sendPhotoBase64();
// void startCameraServer(httpd_handle_t* serverHandle);
extern uint8_t* jpegCopy;
extern size_t jpegLen;

#endif