#ifndef TASK_H
#define TASK_H
#include <stdbool.h>
#include <stdint.h>

#define DEBOUNCE_SAMPLES 4u

typedef struct {
    bool state;      /* current debounced output */
    uint8_t count;   /* consecutive raw samples different from state */
} debounce_t;

void debounce_init(debounce_t *d, bool initial);

/* Feed one raw sample; returns the debounced output after this sample. */
bool debounce_update(debounce_t *d, bool raw);

#endif
