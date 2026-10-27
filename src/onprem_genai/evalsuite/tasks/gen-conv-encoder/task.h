#ifndef TASK_H
#define TASK_H
#include <stddef.h>
#include <stdint.h>

/* Rate 1/2, constraint length 3. Input bits are read MSB first from in[] (bit k is
   (in[k / 8] >> (7 - k % 8)) & 1). With u the current input bit and p1, p2 the previous two input bits
   (both 0 at start):
       out0 = u ^ p1 ^ p2    (generator 7 = 111b)
       out1 = u ^ p2         (generator 5 = 101b)
   For each input bit, out0 then out1 are appended to the output, packed MSB first into out[].
   Unused low bits of the last output byte are set to 0. No tail bits are appended.
   Returns the number of output bits (2 * nbits). out must hold (2 * nbits + 7) / 8 bytes. */
size_t conv_encode(const uint8_t *in, size_t nbits, uint8_t *out);

#endif
