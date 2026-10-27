#include "task.h"
#include "oge_test.h"

int main(void)
{
    CHECK(tick_elapsed(200u, 100u, 100u));
    CHECK(!tick_elapsed(199u, 100u, 100u));
    CHECK(tick_elapsed(0x10u, 0xFFFFFFF0u, 0x20u));
    CHECK(!tick_elapsed(0x0Fu, 0xFFFFFFF0u, 0x20u));
    CHECK(!tick_elapsed(0xFFFFFFF8u, 0xFFFFFFF0u, 0x20u));
    CHECK(tick_elapsed(5u, 5u, 0u));
    CHECK_EQ_U(tick_remaining(150u, 100u, 100u), 50u);
    CHECK_EQ_U(tick_remaining(300u, 100u, 100u), 0u);
    CHECK_EQ_U(tick_remaining(0x0Fu, 0xFFFFFFF0u, 0x20u), 1u);
    CHECK_EQ_U(tick_remaining(0x30u, 0xFFFFFFF0u, 0x20u), 0u);
    return OGE_REPORT();
}
