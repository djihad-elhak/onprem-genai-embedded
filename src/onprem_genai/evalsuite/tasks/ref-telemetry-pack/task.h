#ifndef TASK_H
#define TASK_H
#include <stdint.h>

/* Housekeeping telemetry packed into 8 bytes, MSB first:
   byte 0: mode (2 bits) | heater on (1) | fault (1) | channel (4)
   bytes 1-2: temperature in 0.1 degC, signed 16-bit, clamped to [-1000, 1500]
   bytes 3-4: bus voltage in mV, unsigned 16-bit, clamped to [0, 40000]
   byte 5: gain (0..63, upper 2 bits = 0; values above 63 are clamped to 63)
   bytes 6-7: packet counter, big endian.
   Fields wider than their bit width are masked (mode & 3, channel & 15, flags != 0 -> 1). */
typedef struct {
    uint8_t mode;
    uint8_t heater_on;
    uint8_t fault;
    uint8_t channel;
    int32_t temp_decic;
    int32_t bus_mv;
    uint8_t gain;
    uint16_t counter;
} hk_t;

void hk_pack(const hk_t *hk, uint8_t out[8]);

#endif
