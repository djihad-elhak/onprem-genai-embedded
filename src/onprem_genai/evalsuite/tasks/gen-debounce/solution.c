#include "task.h"

void debounce_init(debounce_t *d, bool initial)
{
    d->state = initial;
    d->count = 0u;
}

bool debounce_update(debounce_t *d, bool raw)
{
    if (raw == d->state) {
        d->count = 0u;
    } else if (++d->count >= DEBOUNCE_SAMPLES) {
        d->state = raw;
        d->count = 0u;
    }
    return d->state;
}
