#include "task.h"
#include "oge_test.h"

int main(void)
{
    const uint8_t abcde[] = {'a', 'b', 'c', 'd', 'e'};
    const uint8_t abcdef[] = {'a', 'b', 'c', 'd', 'e', 'f'};
    const uint8_t abcdefgh[] = {'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'};
    uint8_t ff[300];
    for (int i = 0; i < 300; ++i) {
        ff[i] = 0xFF;
    }
    CHECK_EQ_U(fletcher16(abcde, 5), 0xC8F0);
    CHECK_EQ_U(fletcher16(abcdef, 6), 0x2057);
    CHECK_EQ_U(fletcher16(abcdefgh, 8), 0x0627);
    CHECK_EQ_U(fletcher16(abcde, 0), 0x0000);
    CHECK_EQ_U(fletcher16(ff, 300), 0x0000);
    {
        /* frame with check bytes: c0 = 255 - ((sum1 + sum2) % 255), c1 = 255 - ((sum1 + c0) % 255) */
        uint8_t frame[7] = {'a', 'b', 'c', 'd', 'e', 0, 0};
        uint16_t f = fletcher16(frame, 5);
        uint8_t s1 = (uint8_t)(f & 0xFF), s2 = (uint8_t)(f >> 8);
        frame[5] = (uint8_t)(255 - ((s1 + s2) % 255));
        frame[6] = (uint8_t)(255 - ((s1 + frame[5]) % 255));
        CHECK_EQ_I(fletcher16_frame_ok(frame, 7), 1);
        frame[2] ^= 0x01;
        CHECK_EQ_I(fletcher16_frame_ok(frame, 7), 0);
        CHECK_EQ_I(fletcher16_frame_ok(frame, 1), 0);
        frame[0] = 0x00;
        CHECK_EQ_I(fletcher16_frame_ok(frame, 1), 0);
    }
    return OGE_REPORT();
}
