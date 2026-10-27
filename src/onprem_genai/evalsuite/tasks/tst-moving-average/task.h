#ifndef TASK_H
#define TASK_H
#include <stdint.h>

#define MAVG_WINDOW 4u

/* Integer moving average over the last MAVG_WINDOW samples. Until the window is full, the average is taken
   over the samples received so far. The average rounds toward zero (C integer division). */
typedef struct {
    int32_t samples[MAVG_WINDOW];
    uint32_t next;   /* index where the next sample is written */
    uint32_t count;  /* number of valid samples (<= MAVG_WINDOW) */
    int32_t sum;
} mavg_t;

void mavg_reset(mavg_t *m);
int32_t mavg_push(mavg_t *m, int32_t sample);  /* returns the average after adding sample */

#endif
