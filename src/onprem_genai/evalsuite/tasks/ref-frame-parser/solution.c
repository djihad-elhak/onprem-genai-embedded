#include "task.h"

#include <string.h>

enum { SYNC0 = 0xEB, SYNC1 = 0x90, HEADER_LEN = 4u, OVERHEAD = 5u, MAX_PAYLOAD = 32u };
enum { TYPE_MIN = 0x10, TYPE_MAX = 0x1F };
enum { ERR_SHORT = -1, ERR_SYNC = -2, ERR_LENGTH = -3, ERR_TYPE = -4, ERR_CHECKSUM = -5 };

static uint8_t checksum(const uint8_t *buf, uint8_t payload_len)
{
    uint8_t x = (uint8_t)(buf[2] ^ buf[3]);
    for (uint8_t i = 0u; i < payload_len; ++i) {
        x ^= buf[HEADER_LEN + i];
    }
    return x;
}

static int check_header(const uint8_t *buf, size_t len)
{
    uint8_t payload_len = buf[2];
    if (buf[0] != SYNC0 || buf[1] != SYNC1) {
        return ERR_SYNC;
    }
    if (payload_len == 0u || payload_len > MAX_PAYLOAD || (size_t)payload_len + OVERHEAD != len) {
        return ERR_LENGTH;
    }
    if (buf[3] < TYPE_MIN || buf[3] > TYPE_MAX) {
        return ERR_TYPE;
    }
    return 0;
}

int frame_parse(const uint8_t *buf, size_t len, uint8_t *type, uint8_t *out)
{
    if (buf == NULL || type == NULL || out == NULL || len < OVERHEAD) {
        return ERR_SHORT;
    }
    int status = check_header(buf, len);
    if (status != 0) {
        return status;
    }
    uint8_t payload_len = buf[2];
    if (checksum(buf, payload_len) != buf[HEADER_LEN + payload_len]) {
        return ERR_CHECKSUM;
    }
    *type = buf[3];
    memcpy(out, &buf[HEADER_LEN], payload_len);
    return payload_len;
}
