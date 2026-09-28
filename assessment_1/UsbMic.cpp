#include <Arduino.h>
#include <AudioStream.h>
#include <StreamIO.h>
#include "UsbMic.h"

// The MMF callback copies PCM into a queue. Only loop() writes to Serial,
// so command replies cannot split an audio frame. No Wi-Fi module is used.
struct Packet { uint32_t sequence; uint8_t pcm[512]; };
static QueueHandle_t packets = NULL;
static SemaphoreHandle_t captureLock = NULL;
static bool enabled = false;
static Packet pending;
static size_t filled = 0;
static uint32_t sequence = 0;

static void* sinkCreate(void* parent) { return parent; }
static void* sinkDestroy(void*) { return NULL; }
static int sinkControl(void*, int, int) { return 0; }
static int sinkHandle(void*, void* input, void*) {
  mm_queue_item_t* item = (mm_queue_item_t*)input;
  xSemaphoreTake(captureLock, portMAX_DELAY);
  if (enabled) {
    const uint8_t* data = (const uint8_t*)item->data_addr;
    size_t size = item->size;
    while (size) {
      size_t amount = min(size, sizeof(pending.pcm) - filled);
      memcpy(pending.pcm + filled, data, amount);
      data += amount; size -= amount; filled += amount;
      if (filled == sizeof(pending.pcm)) {
        pending.sequence = sequence++; // Gaps expose queue overruns to the PC.
        xQueueSend(packets, &pending, 0);
        filled = 0;
      }
    }
  }
  xSemaphoreGive(captureLock);
  return 0;
}
static mm_module_t sinkModule = {
  sinkCreate, sinkDestroy, sinkControl, sinkHandle,
  NULL, NULL, NULL, NULL, MM_TYPE_NONE, MM_TYPE_ASINK, "USB_PCM"
};
class UsbSink: public MMFModule {
public:
  bool begin() { _p_mmf_context = mm_module_open(&sinkModule); return _p_mmf_context != NULL; }
};
static AudioSetting config(1); // 16 kHz, 16-bit, mono onboard analogue microphone
static Audio audio;
static UsbSink sink;
static StreamIO link(1, 1);

bool beginUsbMic() {
  packets = xQueueCreate(32, sizeof(Packet));
  captureLock = xSemaphoreCreateMutex();
  if (!packets || !captureLock || !sink.begin()) return false;
  audio.configAudio(config);
  audio.begin();
  link.registerInput(audio);
  link.registerOutput(sink);
  return link.begin() == 0;
}
void setUsbMic(bool value) {
  if (!captureLock) return;
  xSemaphoreTake(captureLock, portMAX_DELAY);
  enabled = value; filled = 0; sequence = 0;
  xQueueReset(packets);
  xSemaphoreGive(captureLock);
}
static uint16_t crcByte(uint16_t crc, uint8_t value) {
  crc ^= (uint16_t)value << 8;
  for (int bit = 0; bit < 8; bit++) crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1;
  return crc;
}
void sendUsbMicFrame() {
  Packet packet;
  if (!packets || xQueueReceive(packets, &packet, 0) != pdTRUE) return;
  static const char hex[] = "0123456789abcdef";
  char line[1080];
  int offset = snprintf(line, sizeof(line), "PCM:%lu:", (unsigned long)packet.sequence);
  uint16_t crc = 0xffff;
  for (int i = 0; i < 4; i++) crc = crcByte(crc, (packet.sequence >> (8 * i)) & 255);
  for (size_t i = 0; i < sizeof(packet.pcm); i++) {
    uint8_t byte = packet.pcm[i];
    crc = crcByte(crc, byte);
    line[offset++] = hex[byte >> 4]; line[offset++] = hex[byte & 15];
  }
  offset += snprintf(line + offset, sizeof(line) - offset, ":%04x\n", crc);
  Serial.write((const uint8_t*)line, offset);
}
