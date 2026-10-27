#include "task.h"

/**
 * @brief Clamp a value to an inclusive range.
 * @param v  Value to clamp.
 * @param lo Lower bound (inclusive).
 * @param hi Upper bound (inclusive), must be >= lo.
 * @return v limited to [lo, hi].
 */
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

/**
 * @brief Initialise a fixed-point PID controller.
 * @param p       Controller state to initialise (non-NULL).
 * @param kp_q8   Proportional gain in Q8 (256 = 1.0).
 * @param ki_q8   Integral gain in Q8.
 * @param kd_q8   Derivative gain in Q8.
 * @param out_min Lowest allowed controller output.
 * @param out_max Highest allowed controller output (>= out_min).
 */
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

/**
 * @brief Run one control step (anti-windup by clamping the integral to +/- integral_limit).
 * @param p           Controller state (updated: integral and previous error).
 * @param setpoint    Desired value, same unit as measurement.
 * @param measurement Measured value.
 * @return Control output (Q8 gains applied, divided by 256), clamped to [out_min, out_max].
 */
int32_t pid_step(pid_t_ *p, int32_t setpoint, int32_t measurement)
{
    int32_t error = setpoint - measurement;
    int32_t derivative = error - p->prev_error;
    p->integral = clamp(p->integral + error, -p->integral_limit, p->integral_limit);
    p->prev_error = error;
    int32_t out = (p->kp_q8 * error + p->ki_q8 * p->integral + p->kd_q8 * derivative) / 256;
    return clamp(out, p->out_min, p->out_max);
}
