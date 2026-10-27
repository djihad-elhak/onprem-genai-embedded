#include "task.h"
#include "oge_test.h"

int main(void)
{
    mode_mgr_t m;
    mode_init(&m);
    CHECK_EQ_I(mode_handle(&m, 2), 0);  CHECK_EQ_U(m.mode, 0);
    CHECK_EQ_I(mode_handle(&m, 4), 0);  CHECK_EQ_U(m.mode, 0);
    CHECK_EQ_I(mode_handle(&m, 0), 1);  CHECK_EQ_U(m.mode, 1);
    CHECK_EQ_I(mode_handle(&m, 0), 0);  CHECK_EQ_U(m.mode, 1);
    CHECK_EQ_I(mode_handle(&m, 3), 0);
    CHECK_EQ_I(mode_handle(&m, 2), 1);  CHECK_EQ_U(m.mode, 2);
    CHECK_EQ_I(mode_handle(&m, 5), 0);
    CHECK_EQ_I(mode_handle(&m, 3), 1);  CHECK_EQ_U(m.mode, 1);
    CHECK_EQ_I(mode_handle(&m, 4), 1);  CHECK_EQ_U(m.mode, 3);
    CHECK_EQ_I(mode_handle(&m, 2), 0);  CHECK_EQ_U(m.mode, 3);
    CHECK_EQ_I(mode_handle(&m, 4), 1);  CHECK_EQ_U(m.mode, 3);
    CHECK_EQ_I(mode_handle(&m, 5), 1);  CHECK_EQ_U(m.mode, 1);
    CHECK_EQ_I(mode_handle(&m, 2), 1);
    CHECK_EQ_I(mode_handle(&m, 4), 1);  CHECK_EQ_U(m.mode, 3);
    CHECK_EQ_I(mode_handle(&m, 1), 1);  CHECK_EQ_U(m.mode, 0);
    CHECK_EQ_I(mode_handle(&m, 1), 1);  CHECK_EQ_U(m.mode, 0);
    CHECK_EQ_I(mode_handle(&m, 9), 0);
    CHECK_EQ_U(m.transitions, 10);
    return OGE_REPORT();
}
