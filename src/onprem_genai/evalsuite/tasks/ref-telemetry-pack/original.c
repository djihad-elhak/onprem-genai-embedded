#include "task.h"

void hk_pack(const hk_t *hk, uint8_t out[8])
{
    int32_t t;
    int32_t v;
    uint8_t g;
    uint8_t b0 = 0;
    b0 = b0 | (uint8_t)((hk->mode & 3) << 6);
    if (hk->heater_on != 0) {
        b0 = b0 | (1 << 5);
    }
    if (hk->fault != 0) {
        b0 = b0 | (1 << 4);
    }
    b0 = b0 | (uint8_t)(hk->channel & 15);
    out[0] = b0;
    t = hk->temp_decic;
    if (t < -1000) {
        t = -1000;
    }
    if (t > 1500) {
        t = 1500;
    }
    out[1] = (uint8_t)(((uint16_t)(int16_t)t >> 8) & 0xFF);
    out[2] = (uint8_t)((uint16_t)(int16_t)t & 0xFF);
    v = hk->bus_mv;
    if (v < 0) {
        v = 0;
    }
    if (v > 40000) {
        v = 40000;
    }
    out[3] = (uint8_t)(((uint32_t)v >> 8) & 0xFF);
    out[4] = (uint8_t)((uint32_t)v & 0xFF);
    g = hk->gain;
    if (g > 63) {
        g = 63;
    }
    out[5] = g;
    out[6] = (uint8_t)((hk->counter >> 8) & 0xFF);
    out[7] = (uint8_t)(hk->counter & 0xFF);
}
