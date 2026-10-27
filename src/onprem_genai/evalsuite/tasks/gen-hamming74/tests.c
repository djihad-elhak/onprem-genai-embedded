#include "task.h"
#include "oge_test.h"

int main(void)
{
    static const uint8_t expected[16] = {0x00, 0x69, 0x2A, 0x43, 0x4C, 0x25, 0x66, 0x0F,
                                         0x70, 0x19, 0x5A, 0x33, 0x3C, 0x55, 0x16, 0x7F};
    for (uint8_t n = 0; n < 16; ++n) {
        uint8_t cw = hamming74_encode(n);
        uint8_t out = 0xFF;
        CHECK_EQ_U(cw, expected[n]);
        CHECK_EQ_U(hamming74_decode(cw, &out), 0);
        CHECK_EQ_U(out, n);
        for (unsigned bit = 0; bit < 7; ++bit) {
            out = 0xFF;
            CHECK_EQ_U(hamming74_decode((uint8_t)(cw ^ (1u << bit)), &out), 1);
            CHECK_EQ_U(out, n);
        }
    }
    {
        uint8_t out = 0;
        CHECK_EQ_U(hamming74_encode(0xF3), hamming74_encode(0x03));
        CHECK_EQ_U(hamming74_decode((uint8_t)(0x80 | expected[5]), &out), 0);
        CHECK_EQ_U(out, 5);
    }
    return OGE_REPORT();
}
