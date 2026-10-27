#ifndef TASK_H
#define TASK_H
#include <stdint.h>

typedef struct {
    int32_t kp_q8;
    int32_t ki_q8;
    int32_t kd_q8;
    int32_t integral;
    int32_t integral_limit;
    int32_t prev_error;
    int32_t out_min;
    int32_t out_max;
} pid_t_;

void pid_init(pid_t_ *p, int32_t kp_q8, int32_t ki_q8, int32_t kd_q8, int32_t out_min, int32_t out_max);
int32_t pid_step(pid_t_ *p, int32_t setpoint, int32_t measurement);

#endif
