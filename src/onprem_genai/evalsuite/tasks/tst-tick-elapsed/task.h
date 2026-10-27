#ifndef TASK_H
#define TASK_H
#include <stdbool.h>
#include <stdint.h>

/* 32-bit free-running millisecond tick (wraps around). Elapsed times are assumed < 2^31 ms. */
bool tick_elapsed(uint32_t now, uint32_t start, uint32_t timeout_ms);
uint32_t tick_remaining(uint32_t now, uint32_t start, uint32_t timeout_ms);

#endif
