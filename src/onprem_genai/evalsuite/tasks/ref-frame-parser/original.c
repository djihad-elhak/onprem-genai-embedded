#include "task.h"

int frame_parse(const uint8_t *buf, size_t len, uint8_t *type, uint8_t *out)
{
    int rc = 0;
    uint8_t x = 0;
    size_t i;
    if (buf == 0 || type == 0 || out == 0) {
        rc = -1;
        goto done;
    }
    if (len < 5) {
        rc = -1;
        goto done;
    }
    if (buf[0] != 0xEB || buf[1] != 0x90) {
        rc = -2;
        goto done;
    }
    if (buf[2] == 0 || buf[2] > 32) {
        rc = -3;
        goto done;
    } else {
        if ((size_t)buf[2] + 5 != len) {
            rc = -3;
            goto done;
        }
    }
    if (buf[3] < 0x10 || buf[3] > 0x1F) {
        rc = -4;
        goto done;
    }
    x = buf[2] ^ buf[3];
    for (i = 0; i < buf[2]; i++) {
        x ^= buf[4 + i];
    }
    if (x != buf[4 + buf[2]]) {
        rc = -5;
        goto done;
    }
    *type = buf[3];
    for (i = 0; i < buf[2]; i++) {
        out[i] = buf[4 + i];
    }
    rc = buf[2];
done:
    return rc;
}
