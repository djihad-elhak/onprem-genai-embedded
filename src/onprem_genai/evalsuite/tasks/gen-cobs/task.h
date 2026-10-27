#ifndef TASK_H
#define TASK_H
#include <stddef.h>
#include <stdint.h>

/* Encode src[0..len) into dst. dst must hold at least len + len / 254 + 1 bytes.
   Returns the encoded length (always >= 1; the encoding of an empty input is {0x01}). */
size_t cobs_encode(const uint8_t *src, size_t len, uint8_t *dst);

/* Decode src[0..len) into dst (capacity >= len). Returns the decoded length, or 0 when the input is
   malformed (len == 0, a 0x00 byte inside src, or a code byte that points past the end). */
size_t cobs_decode(const uint8_t *src, size_t len, uint8_t *dst);

#endif
