// Onboard microphone and LED control share the USB UART cable. No Wi-Fi.
#include "UsbMic.h"
extern "C" {
#include "serial_api.h"
}
extern serial_t log_uart_obj;
const int BLUE_LED = 23, GREEN_LED = 24;
bool audioReady = false, lit = false;
int activeMask = 0, remaining = 0; // bit 0: blue, bit 1: green
unsigned long lastToggle = 0;
char input[96];
size_t used = 0;
bool overflow = false;

void allOff() {
  digitalWrite(BLUE_LED, LOW); digitalWrite(GREEN_LED, LOW);
  lit = false; activeMask = 0; remaining = 0;
}
void writeLights() {
  digitalWrite(BLUE_LED, lit && (activeMask & 1) ? HIGH : LOW);
  digitalWrite(GREEN_LED, lit && (activeMask & 2) ? HIGH : LOW);
}
void startLight(int mask, int count) {
  allOff();
  activeMask = mask;
  remaining = count;
  lit = true; lastToggle = millis();
  writeLights();
}
void tickLight() {
  if (activeMask == 0 || remaining == 0 || millis() - lastToggle < 300) return;
  lastToggle = millis();
  lit = !lit;
  writeLights();
  if (!lit && --remaining == 0) activeMask = 0;
}
void handleCommand() {
  input[used] = 0;
  unsigned long id;
  char color[8], extra;
  int count;
  if (strcmp(input, "INFO") == 0) {
    Serial.print("INFO:VOICE_LED_V3:");
    Serial.println(audioReady ? "USB_PCM_16000" : "MIC_ERROR");
  } else if (sscanf(input, "MIC %lu %d %c", &id, &count, &extra) == 2
             && (count == 0 || count == 1)) {
    if (!audioReady) { Serial.println("ERR:MIC_INIT"); return; }
    setUsbMic(count == 1);
    Serial.print("MIC:"); Serial.print(id); Serial.print(":"); Serial.println(count);
  } else if (sscanf(input, "SET %lu %7s %d %c", &id, color, &count, &extra) == 3
             && count >= 0 && count <= 100
             && (!strcmp(color, "BLUE") || !strcmp(color, "GREEN") || !strcmp(color, "BOTH") || !strcmp(color, "OFF"))) {
    if (!strcmp(color, "OFF")) allOff();
    else startLight(!strcmp(color, "BLUE") ? 1 : !strcmp(color, "GREEN") ? 2 : 3, count);
    Serial.print("OK:"); Serial.print(id); Serial.print(":");
    Serial.print(color); Serial.print(":"); Serial.println(count);
  } else if (sscanf(input, "STATE %lu %c", &id, &extra) == 1) {
    Serial.print("STATE:"); Serial.print(id); Serial.print(":");
    Serial.print(activeMask == 3 ? "BOTH" : activeMask == 1 ? "BLUE" : activeMask == 2 ? "GREEN" : "OFF");
    Serial.print(":"); Serial.print(remaining); Serial.print(":"); Serial.println(lit ? 1 : 0);
  } else Serial.println("ERR:INVALID_COMMAND");
}
void readCommands() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (overflow) Serial.println("ERR:COMMAND_TOO_LONG");
      else if (used) handleCommand();
      used = 0; overflow = false;
    } else if (!overflow) {
      if (used < sizeof(input) - 1) input[used++] = c;
      else overflow = true;
    }
  }
}
void setup() {
  Serial.begin(115200);
  // SDK 4.0.9 forces Serial.begin() to 115200; set the existing UART via HAL.
  serial_baud(&log_uart_obj, 921600);
  pinMode(BLUE_LED, OUTPUT); pinMode(GREEN_LED, OUTPUT);
  allOff();
  audioReady = beginUsbMic();
  Serial.println("BOOT:VOICE_LED_V3");
}
void loop() {
  readCommands(); tickLight();
  sendUsbMicFrame();
  delay(1);
}

