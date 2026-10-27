#ifndef TASK_H
#define TASK_H
#include <stddef.h>
#include <stdint.h>

/* CRC-16/CCITT-FALSE of data[0..len): poly 0x1021, init 0xFFFF, no reflection, xorout 0x0000. */
uint16_t crc16_ccitt_false(const uint8_t *data, size_t len);

/* Continue a CRC: crc16_ccitt_update(crc16_ccitt_false(a, n), b, m) == CRC of a followed by b.
   crc16_ccitt_update(0xFFFF, d, n) == crc16_ccitt_false(d, n). data may be NULL when len == 0. */
uint16_t crc16_ccitt_update(uint16_t crc, const uint8_t *data, size_t len);

#endif
