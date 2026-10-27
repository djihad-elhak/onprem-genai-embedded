#ifndef TASK_H
#define TASK_H
#include <stdbool.h>
#include <stdint.h>

/* true iff at least timeout_ms milliseconds have passed between start and now (modulo 2^32). */
bool tick_elapsed(uint32_t now, uint32_t start, uint32_t timeout_ms);

/* milliseconds remaining before the timeout expires, 0 if already elapsed. */
uint32_t tick_remaining(uint32_t now, uint32_t start, uint32_t timeout_ms);

#endif
