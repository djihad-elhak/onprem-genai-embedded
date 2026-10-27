#ifndef TASK_H
#define TASK_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define RB_CAPACITY 7u

typedef struct {
    uint8_t data[RB_CAPACITY];
    size_t head;  /* next write index */
    size_t tail;  /* next read index */
    size_t count; /* number of stored bytes */
} ring_buffer_t;

void rb_init(ring_buffer_t *rb);
bool rb_push(ring_buffer_t *rb, uint8_t byte);      /* false when full (nothing stored) */
bool rb_pop(ring_buffer_t *rb, uint8_t *out);       /* false when empty (*out untouched) */
size_t rb_count(const ring_buffer_t *rb);
bool rb_is_full(const ring_buffer_t *rb);
size_t rb_push_many(ring_buffer_t *rb, const uint8_t *src, size_t n); /* stores as many as fit, returns count */

#endif
