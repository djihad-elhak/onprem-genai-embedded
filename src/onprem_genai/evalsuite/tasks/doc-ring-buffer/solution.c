#include "task.h"

/**
 * @brief rb init.
 * @param rb Input `rb`.
 */
void rb_init(ring_buffer_t *rb)
{
    rb->head = 0u;
    rb->tail = 0u;
    rb->count = 0u;
}

/**
 * @brief rb push.
 * @param rb Input `rb`.
 * @param byte Input `byte`.
 * @return Result, see task.h for ranges and error codes.
 */
bool rb_push(ring_buffer_t *rb, uint8_t byte)
{
    if (rb->count >= RB_CAPACITY) {
        return false;
    }
    rb->data[rb->head] = byte;
    rb->head = (rb->head + 1u) % RB_CAPACITY;
    rb->count++;
    return true;
}

/**
 * @brief rb pop.
 * @param rb Input `rb`.
 * @param out Input `out`.
 * @return Result, see task.h for ranges and error codes.
 */
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

/**
 * @brief rb count.
 * @param rb Input `rb`.
 * @return Result, see task.h for ranges and error codes.
 */
size_t rb_count(const ring_buffer_t *rb) { return rb->count; }

/**
 * @brief rb push many.
 * @param rb Input `rb`.
 * @param src Input `src`.
 * @param n Input `n`.
 * @return Result, see task.h for ranges and error codes.
 */
size_t rb_push_many(ring_buffer_t *rb, const uint8_t *src, size_t n)
{
    size_t stored = 0u;
    while (stored < n && rb_push(rb, src[stored])) {
        stored++;
    }
    return stored;
}
