#include "task.h"

uint32_t crc32_ieee_update(uint32_t crc, const uint8_t *data, size_t len)
{
    crc = ~crc;
    for (size_t i = 0; i < len; ++i) {
        crc ^= data[i];
        for (int b = 0; b < 8; ++b) {
            crc = (crc & 1u) ? (crc >> 1) ^ 0xEDB88320u : crc >> 1;
        }
    }
    return ~crc;
}

uint32_t crc32_ieee(const uint8_t *data, size_t len)
{
    return crc32_ieee_update(0u, data, len);
}
