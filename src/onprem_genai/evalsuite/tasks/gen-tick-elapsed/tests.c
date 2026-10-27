#include "task.h"
#include "oge_test.h"

int main(void)
{
    CHECK(!tick_elapsed(100, 0, 101));
    CHECK(tick_elapsed(101, 0, 101));
    CHECK(tick_elapsed(5000, 1000, 4000));
    CHECK(!tick_elapsed(4999, 1000, 4000));
    CHECK(tick_elapsed(0x10u, 0xFFFFFFF0u, 0x20u));
    CHECK(!tick_elapsed(0x0Fu, 0xFFFFFFF0u, 0x20u));
    CHECK(tick_elapsed(0x00000005u, 0xFFFFFFFBu, 10u));
    CHECK(!tick_elapsed(0x00000004u, 0xFFFFFFFBu, 10u));
    CHECK(tick_elapsed(123u, 123u, 0u));
    CHECK_EQ_U(tick_remaining(0x0Fu, 0xFFFFFFF0u, 0x20u), 1u);
    CHECK_EQ_U(tick_remaining(0x10u, 0xFFFFFFF0u, 0x20u), 0u);
    CHECK_EQ_U(tick_remaining(1000u, 1000u, 250u), 250u);
    CHECK_EQ_U(tick_remaining(0x7FFFFFFFu, 0u, 0xFFFFFFFFu), 0x80000000u);
    CHECK_EQ_U(tick_remaining(0xFFFFFFFFu, 0xFFFFFFFFu, 7u), 7u);
    return OGE_REPORT();
}
