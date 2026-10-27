#ifndef TASK_H
#define TASK_H
#include <stddef.h>
#include <stdint.h>

/* Frame: SYNC (0xEB 0x90) | LEN (1 byte, payload length 1..32) | TYPE (1 byte, 0x10..0x1F) | PAYLOAD | XOR
   where XOR is the XOR of LEN, TYPE and every payload byte.
   frame_parse copies the payload to out (capacity >= 32) and returns its length, or:
   -1 too short / NULL, -2 bad sync, -3 bad length (0, > 32, or not matching the buffer size exactly),
   -4 bad type, -5 bad checksum. */
int frame_parse(const uint8_t *buf, size_t len, uint8_t *type, uint8_t *out);

#endif
