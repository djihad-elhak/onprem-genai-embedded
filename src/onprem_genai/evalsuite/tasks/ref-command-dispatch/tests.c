#include "task.h"
#include "oge_test.h"

int main(void)
{
    payload_state_t s;
    payload_init(&s);
    CHECK_EQ_U(s.mode, 0); CHECK_EQ_U(s.gain, 10); CHECK_EQ_U(s.channel, 1);
    CHECK_EQ_I(payload_dispatch(&s, 2, 5), -3);
    CHECK_EQ_I(payload_dispatch(&s, 3, 5), -3);
    CHECK_EQ_I(payload_dispatch(&s, 1, 4), -2);
    CHECK_EQ_I(payload_dispatch(&s, 1, 2), 0);
    CHECK_EQ_U(s.mode, 2);
    CHECK_EQ_I(payload_dispatch(&s, 2, 63), 0);
    CHECK_EQ_I(payload_dispatch(&s, 2, 64), -2);
    CHECK_EQ_U(s.gain, 63);
    CHECK_EQ_I(payload_dispatch(&s, 3, 0), -2);
    CHECK_EQ_I(payload_dispatch(&s, 3, 16), -2);
    CHECK_EQ_I(payload_dispatch(&s, 3, 15), 0);
    CHECK_EQ_U(s.channel, 15);
    CHECK_EQ_I(payload_dispatch(&s, 5, 77), 0);
    CHECK_EQ_I(payload_dispatch(&s, 4, 0), -2);
    CHECK_EQ_I(payload_dispatch(&s, 4, 0xA5), 0);
    CHECK_EQ_U(s.mode, 0); CHECK_EQ_U(s.gain, 10); CHECK_EQ_U(s.channel, 1);
    CHECK_EQ_I(payload_dispatch(&s, 0, 0), -1);
    CHECK_EQ_I(payload_dispatch(&s, 6, 0), -1);
    CHECK_EQ_I(payload_dispatch(&s, 0xFF, 0), -1);
    CHECK_EQ_U(s.cmd_count, 5);
    CHECK_EQ_U(s.err_count, 10);
    return OGE_REPORT();
}
