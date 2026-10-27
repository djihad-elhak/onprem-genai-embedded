/* Minimal C99 test framework used by the evaluation suite (hidden tests and model-written tests).
 *
 *   CHECK(cond)              boolean check
 *   CHECK_EQ_U(a, b)         unsigned comparison, prints both values on failure
 *   CHECK_EQ_I(a, b)         signed comparison
 *   CHECK_MEM(a, b, n)       byte-wise comparison of n bytes
 *   return OGE_REPORT();     at the end of main(): prints counts, exit code 1 on any failure
 */
#ifndef OGE_TEST_H
#define OGE_TEST_H

#include <stdio.h>
#include <string.h>

static int oge_checks = 0;
static int oge_failures = 0;

#define CHECK(cond)                                                                    \
    do {                                                                               \
        oge_checks++;                                                                  \
        if (!(cond)) {                                                                 \
            oge_failures++;                                                            \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond);   \
        }                                                                              \
    } while (0)

#define CHECK_EQ_U(a, b)                                                               \
    do {                                                                               \
        unsigned long long oge_a = (unsigned long long)(a);                            \
        unsigned long long oge_b = (unsigned long long)(b);                            \
        oge_checks++;                                                                  \
        if (oge_a != oge_b) {                                                          \
            oge_failures++;                                                            \
            fprintf(stderr, "%s:%d: %s == %s failed: 0x%llx != 0x%llx\n", __FILE__,    \
                    __LINE__, #a, #b, oge_a, oge_b);                                   \
        }                                                                              \
    } while (0)

#define CHECK_EQ_I(a, b)                                                               \
    do {                                                                               \
        long long oge_a = (long long)(a);                                              \
        long long oge_b = (long long)(b);                                              \
        oge_checks++;                                                                  \
        if (oge_a != oge_b) {                                                          \
            oge_failures++;                                                            \
            fprintf(stderr, "%s:%d: %s == %s failed: %lld != %lld\n", __FILE__,        \
                    __LINE__, #a, #b, oge_a, oge_b);                                   \
        }                                                                              \
    } while (0)

#define CHECK_MEM(a, b, n)                                                             \
    do {                                                                               \
        oge_checks++;                                                                  \
        if (memcmp((a), (b), (n)) != 0) {                                              \
            oge_failures++;                                                            \
            fprintf(stderr, "%s:%d: memory differs: %s vs %s\n", __FILE__, __LINE__,  \
                    #a, #b);                                                           \
        }                                                                              \
    } while (0)

#define OGE_REPORT()                                                                   \
    (printf("checks=%d failures=%d\n", oge_checks, oge_failures), oge_failures ? 1 : 0)

#endif /* OGE_TEST_H */
