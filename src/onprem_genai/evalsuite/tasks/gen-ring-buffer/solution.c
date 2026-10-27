#include "task.h"

void rb_init(ring_buffer_t *rb)
{
    rb->head = 0u;
    rb->tail = 0u;
    rb->count = 0u;
}

bool rb_push(ring_buffer_t *rb, uint8_t byte)
{
    if (rb->count == RB_CAPACITY) {
        return false;
    }
    rb->data[rb->head] = byte;
    rb->head = (rb->head + 1u) % RB_CAPACITY;
    rb->count++;
    return true;
}

bool rb_pop(ring_buffer_t *rb, uint8_t *out)
{
    if (rb->count == 0u) {
        return false;
    }
    *out = rb->data[rb->tail];
    rb->tail = (rb->tail + 1u) % RB_CAPACITY;
    rb->count--;
    return true;
}

size_t rb_count(const ring_buffer_t *rb) { return rb->count; }

bool rb_is_full(const ring_buffer_t *rb) { return rb->count == RB_CAPACITY; }

size_t rb_push_many(ring_buffer_t *rb, const uint8_t *src, size_t n)
{
    size_t stored = 0u;
    while (stored < n && rb_push(rb, src[stored])) {
        stored++;
    }
    return stored;
}
