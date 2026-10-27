#include "task.h"
#include "oge_test.h"

static size_t make(uint8_t *f, uint8_t len, uint8_t type)
{
    uint8_t x = len ^ type;
    f[0] = 0xEB; f[1] = 0x90; f[2] = len; f[3] = type;
    for (uint8_t i = 0; i < len; ++i) {
        f[4 + i] = (uint8_t)(i * 7 + 1);
        x ^= f[4 + i];
    }
    f[4 + len] = x;
    return (size_t)len + 5;
}

int main(void)
{
    uint8_t f[64], out[32], type = 0;
    size_t n = make(f, 3, 0x12);
    CHECK_EQ_I(frame_parse(f, n, &type, out), 3);
    CHECK_EQ_U(type, 0x12);
    CHECK_EQ_U(out[0], 1); CHECK_EQ_U(out[1], 8); CHECK_EQ_U(out[2], 15);
    n = make(f, 32, 0x1F);
    CHECK_EQ_I(frame_parse(f, n, &type, out), 32);
    CHECK_EQ_I(frame_parse(f, n - 1, &type, out), -3);
    CHECK_EQ_I(frame_parse(f, 4, &type, out), -1);
    CHECK_EQ_I(frame_parse(NULL, n, &type, out), -1);
    CHECK_EQ_I(frame_parse(f, n, NULL, out), -1);
    n = make(f, 2, 0x10); f[1] = 0x91;
    CHECK_EQ_I(frame_parse(f, n, &type, out), -2);
    n = make(f, 2, 0x20);
    CHECK_EQ_I(frame_parse(f, n, &type, out), -4);
    n = make(f, 2, 0x0F);
    CHECK_EQ_I(frame_parse(f, n, &type, out), -4);
    n = make(f, 2, 0x11); f[5] ^= 0x40;
    CHECK_EQ_I(frame_parse(f, n, &type, out), -5);
    f[0] = 0xEB; f[1] = 0x90; f[2] = 0; f[3] = 0x11; f[4] = 0x11;
    CHECK_EQ_I(frame_parse(f, 5, &type, out), -3);
    n = make(f, 33, 0x11);
    CHECK_EQ_I(frame_parse(f, n, &type, out), -3);
    return OGE_REPORT();
}
