#include "task.h"
#include <stdbool.h>

size_t cobs_encode(const uint8_t *src, size_t len, uint8_t *dst)
{
    size_t out = 1u;
    size_t code_idx = 0u;
    uint8_t code = 1u;
    bool open = true;
    for (size_t i = 0u; i < len; ++i) {
        if (src[i] != 0u) {
            dst[out++] = src[i];
            code++;
        }
        if (src[i] == 0u || code == 0xFFu) {
            dst[code_idx] = code;
            code = 1u;
            if (src[i] == 0u || i + 1u < len) {
                code_idx = out++;
            } else {
                open = false;
            }
        }
    }
    if (open) {
        dst[code_idx] = code;
    }
    return out;
}

size_t cobs_decode(const uint8_t *src, size_t len, uint8_t *dst)
{
    size_t in = 0u;
    size_t out = 0u;
    if (len == 0u) {
        return 0u;
    }
    while (in < len) {
        uint8_t code = src[in];
        if (code == 0u || in + code > len) {
            return 0u;
        }
        in++;
        for (uint8_t k = 1u; k < code; ++k) {
            if (src[in] == 0u) {
                return 0u;
            }
            dst[out++] = src[in++];
        }
        if (code != 0xFFu && in < len) {
            dst[out++] = 0u;
        }
    }
    return out;
}
