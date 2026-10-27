#include "task.h"

static uint8_t bit_at(uint8_t cw, unsigned pos) { return (uint8_t)((cw >> (7u - pos)) & 1u); }

uint8_t hamming74_encode(uint8_t nibble)
{
    uint8_t d1 = (nibble >> 3) & 1u, d2 = (nibble >> 2) & 1u, d3 = (nibble >> 1) & 1u, d4 = nibble & 1u;
    uint8_t p1 = d1 ^ d2 ^ d4, p2 = d1 ^ d3 ^ d4, p3 = d2 ^ d3 ^ d4;
    return (uint8_t)((p1 << 6) | (p2 << 5) | (d1 << 4) | (p3 << 3) | (d2 << 2) | (d3 << 1) | d4);
}

int hamming74_decode(uint8_t codeword, uint8_t *nibble)
{
    uint8_t cw = codeword & 0x7Fu;
    unsigned s1 = bit_at(cw, 1) ^ bit_at(cw, 3) ^ bit_at(cw, 5) ^ bit_at(cw, 7);
    unsigned s2 = bit_at(cw, 2) ^ bit_at(cw, 3) ^ bit_at(cw, 6) ^ bit_at(cw, 7);
    unsigned s3 = bit_at(cw, 4) ^ bit_at(cw, 5) ^ bit_at(cw, 6) ^ bit_at(cw, 7);
    unsigned syndrome = s1 | (s2 << 1) | (s3 << 2);
    if (syndrome != 0u) {
        cw ^= (uint8_t)(1u << (7u - syndrome));
    }
    *nibble = (uint8_t)((bit_at(cw, 3) << 3) | (bit_at(cw, 5) << 2) | (bit_at(cw, 6) << 1) | bit_at(cw, 7));
    return syndrome != 0u;
}
