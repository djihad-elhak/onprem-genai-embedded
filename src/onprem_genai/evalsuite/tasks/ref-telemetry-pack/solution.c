#include "task.h"

enum { MODE_MASK = 0x3u, CHANNEL_MASK = 0xFu, MODE_SHIFT = 6u, HEATER_BIT = 5u, FAULT_BIT = 4u };
enum { TEMP_MIN = -1000, TEMP_MAX = 1500, BUS_MIN = 0, BUS_MAX = 40000, GAIN_MAX = 63u };

static int32_t clamp(int32_t v, int32_t lo, int32_t hi) { return v < lo ? lo : (v > hi ? hi : v); }

static void put_be16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v >> 8);
    p[1] = (uint8_t)v;
}

static uint8_t status_byte(const hk_t *hk)
{
    return (uint8_t)(((hk->mode & MODE_MASK) << MODE_SHIFT) | ((hk->heater_on != 0u) << HEATER_BIT) |
                     ((hk->fault != 0u) << FAULT_BIT) | (hk->channel & CHANNEL_MASK));
}

void hk_pack(const hk_t *hk, uint8_t out[8])
{
    out[0] = status_byte(hk);
    put_be16(&out[1], (uint16_t)(int16_t)clamp(hk->temp_decic, TEMP_MIN, TEMP_MAX));
    put_be16(&out[3], (uint16_t)clamp(hk->bus_mv, BUS_MIN, BUS_MAX));
    out[5] = hk->gain > GAIN_MAX ? (uint8_t)GAIN_MAX : hk->gain;
    put_be16(&out[6], hk->counter);
}
