#include "task.h"
#include "oge_test.h"

int main(void)
{
    CHECK_EQ_I(sat_add16(1000, 2000), 3000);
    CHECK_EQ_I(sat_add16(32000, 1000), 32767);
    CHECK_EQ_I(sat_add16(32767, 0), 32767);
    CHECK_EQ_I(sat_add16(32766, 1), 32767);
    CHECK_EQ_I(sat_add16(-32000, -1000), -32768);
    CHECK_EQ_I(sat_add16(-32767, -1), -32768);
    CHECK_EQ_I(sat_add16(-5, 3), -2);
    CHECK_EQ_I(sat_add16(-5, -3), -8);
    CHECK_EQ_I(sat_sub16(-32000, 1000), -32768);
    CHECK_EQ_I(sat_sub16(32000, -1000), 32767);
    CHECK_EQ_I(sat_sub16(5, 7), -2);
    CHECK_EQ_I(sat_sub16(0, -32768), 32767);
    CHECK_EQ_I(sat_abs16(-32768), 32767);
    CHECK_EQ_I(sat_abs16(-5), 5);
    CHECK_EQ_I(sat_abs16(7), 7);
    CHECK_EQ_I(sat_abs16(0), 0);
    return OGE_REPORT();
}
