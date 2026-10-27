#include "task.h"

static int32_t clamp(int32_t v, int32_t lo, int32_t hi)
{
    if (v < lo) {
        return lo;
    }
    if (v > hi) {
        return hi;
    }
    return v;
}

void pid_init(pid_t_ *p, int32_t kp_q8, int32_t ki_q8, int32_t kd_q8, int32_t out_min, int32_t out_max)
{
    p->kp_q8 = kp_q8;
    p->ki_q8 = ki_q8;
    p->kd_q8 = kd_q8;
    p->integral = 0;
    p->integral_limit = 100000;
    p->prev_error = 0;
    p->out_min = out_min;
    p->out_max = out_max;
}

int32_t pid_step(pid_t_ *p, int32_t setpoint, int32_t measurement)
{
    int32_t error = setpoint - measurement;
    int32_t derivative = error - p->prev_error;
    p->integral = clamp(p->integral + error, -p->integral_limit, p->integral_limit);
    p->prev_error = error;
    int32_t out = (p->kp_q8 * error + p->ki_q8 * p->integral + p->kd_q8 * derivative) / 256;
    return clamp(out, p->out_min, p->out_max);
}
