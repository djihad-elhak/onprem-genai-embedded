#include "task.h"
#include "oge_test.h"
#include <string.h>

int main(void)
{
    { static const uint8_t in[] = {0x80}; static const uint8_t ex[] = {0xC0};
      uint8_t out[32]; memset(out, 0xA5, sizeof out);
      CHECK_EQ_U(conv_encode(in, 1, out), 2); CHECK_MEM(out, ex, 1); } /* case 0 */
    { static const uint8_t in[] = {0xB4}; static const uint8_t ex[] = {0xE1, 0x40};
      uint8_t out[32]; memset(out, 0xA5, sizeof out);
      CHECK_EQ_U(conv_encode(in, 6, out), 12); CHECK_MEM(out, ex, 2); } /* case 1 */
    { static const uint8_t in[] = {0xFF, 0x00}; static const uint8_t ex[] = {0xDA, 0xAA, 0x70, 0x00};
      uint8_t out[32]; memset(out, 0xA5, sizeof out);
      CHECK_EQ_U(conv_encode(in, 16, out), 32); CHECK_MEM(out, ex, 4); } /* case 2 */
    { static const uint8_t in[] = {0x82, 0xB7, 0x0E, 0xEE, 0x7F, 0x1A, 0x50, 0x39, 0xBE}; static const uint8_t ex[] = {0xEC, 0x0E, 0x21, 0x46, 0x70, 0xD9, 0x19, 0x19, 0xF6, 0xAA, 0x73, 0x52, 0xF8, 0xB0, 0x0D, 0x9F, 0x51, 0x80};
      uint8_t out[32]; memset(out, 0xA5, sizeof out);
      CHECK_EQ_U(conv_encode(in, 69, out), 138); CHECK_MEM(out, ex, 18); } /* case 3 */
    { static const uint8_t in[] = {0x00}; static const uint8_t ex[] = {0x00, 0x00};
      uint8_t out[32]; memset(out, 0xA5, sizeof out);
      CHECK_EQ_U(conv_encode(in, 8, out), 16); CHECK_MEM(out, ex, 2); } /* case 4 */
    return OGE_REPORT();
}
