#include "task.h"
#include "oge_test.h"

int main(void)
{
    pid_t_ p;
    pid_init(&p, 512, 0, 0, -1000, 1000);
    CHECK_EQ_I(pid_step(&p, 100, 40), 120);
    CHECK_EQ_I(pid_step(&p, 1000, 0), 1000);
    pid_init(&p, 0, 256, 0, -50, 50);
    CHECK_EQ_I(pid_step(&p, 10, 0), 10);
    CHECK_EQ_I(pid_step(&p, 10, 0), 20);
    CHECK_EQ_I(pid_step(&p, -100, 0), -50);
    pid_init(&p, 0, 0, 256, -500, 500);
    CHECK_EQ_I(pid_step(&p, 5, 0), 5);
    CHECK_EQ_I(pid_step(&p, 5, 0), 0);
    return OGE_REPORT();
}
