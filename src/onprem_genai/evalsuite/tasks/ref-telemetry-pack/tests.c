#include "task.h"
#include "oge_test.h"

int main(void)
{
    uint8_t out[8];
    hk_t hk = {2, 1, 0, 9, 235, 28123, 17, 0x1234};
    const uint8_t e1[8] = {0xA9, 0x00, 0xEB, 0x6D, 0xDB, 0x11, 0x12, 0x34};
    hk_pack(&hk, out);
    CHECK_MEM(out, e1, 8);
    hk.mode = 7; hk.heater_on = 0; hk.fault = 5; hk.channel = 0x1F;
    hk.temp_decic = -2000; hk.bus_mv = -5; hk.gain = 200; hk.counter = 0xFFFF;
    {
        const uint8_t e2[8] = {0xDF, 0xFC, 0x18, 0x00, 0x00, 0x3F, 0xFF, 0xFF};
        hk_pack(&hk, out);
        CHECK_MEM(out, e2, 8);
    }
    hk.temp_decic = 99999; hk.bus_mv = 99999; hk.gain = 63;
    {
        const uint8_t e3[8] = {0xDF, 0x05, 0xDC, 0x9C, 0x40, 0x3F, 0xFF, 0xFF};
        hk_pack(&hk, out);
        CHECK_MEM(out, e3, 8);
    }
    return OGE_REPORT();
}
