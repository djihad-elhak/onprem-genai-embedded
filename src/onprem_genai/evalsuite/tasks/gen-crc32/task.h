#ifndef TASK_H
#define TASK_H
#include <stddef.h>
#include <stdint.h>

/* CRC-32/ISO-HDLC of data[0..len). crc32_ieee("123456789", 9) == 0xCBF43926. */
uint32_t crc32_ieee(const uint8_t *data, size_t len);

/* Incremental: crc32_ieee_update(crc32_ieee(a, n), b, m) == CRC-32 of a followed by b;
   crc32_ieee_update(0, d, n) == crc32_ieee(d, n). data may be NULL when len == 0. */
uint32_t crc32_ieee_update(uint32_t crc, const uint8_t *data, size_t len);

#endif
