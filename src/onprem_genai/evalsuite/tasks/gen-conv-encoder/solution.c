#include "task.h"
#include <string.h>

size_t conv_encode(const uint8_t *in, size_t nbits, uint8_t *out)
{
    unsigned p1 = 0u, p2 = 0u;
    size_t o = 0u;
    memset(out, 0, (2u * nbits + 7u) / 8u);
    for (size_t k = 0u; k < nbits; ++k) {
        unsigned u = (in[k / 8u] >> (7u - k % 8u)) & 1u;
        unsigned b0 = u ^ p1 ^ p2;
        unsigned b1 = u ^ p2;
        out[o / 8u] |= (uint8_t)(b0 << (7u - o % 8u));
        o++;
        out[o / 8u] |= (uint8_t)(b1 << (7u - o % 8u));
        o++;
        p2 = p1;
        p1 = u;
    }
    return o;
}
