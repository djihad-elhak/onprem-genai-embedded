#include "task.h"
#include "oge_test.h"

int main(void)
{
    mavg_t m;
    mavg_reset(&m);
    CHECK_EQ_I(mavg_push(&m, 10), 10);
    CHECK_EQ_I(mavg_push(&m, 20), 15);
    CHECK_EQ_I(mavg_push(&m, 30), 20);
    CHECK_EQ_I(mavg_push(&m, 40), 25);
    CHECK_EQ_I(mavg_push(&m, 50), 35);
    CHECK_EQ_I(mavg_push(&m, 60), 45);
    CHECK_EQ_I(mavg_push(&m, 70), 55);
    CHECK_EQ_I(mavg_push(&m, 80), 65);
    CHECK_EQ_I(mavg_push(&m, 81), 72);
    mavg_reset(&m);
    CHECK_EQ_I(mavg_push(&m, -7), -7);
    CHECK_EQ_I(mavg_push(&m, 0), -3);
    CHECK_EQ_I(mavg_push(&m, 2), -1);
    mavg_reset(&m);
    CHECK_EQ_I(mavg_push(&m, 5), 5);
    CHECK_EQ_U(m.count, 1u);
    return OGE_REPORT();
}
