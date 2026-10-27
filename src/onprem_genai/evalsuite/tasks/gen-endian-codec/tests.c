#include "task.h"
#include "oge_test.h"

int main(void)
{
    uint8_t buf[11] = {0x00, 0xFE, 0xDC, 0xBA, 0x98, 0x80, 0x01, 0x02, 0x03, 0x04, 0xFF};
    CHECK_EQ_U(read_be16(buf + 1), 0xFEDC);
    CHECK_EQ_U(read_le16(buf + 1), 0xDCFE);
    CHECK_EQ_U(read_be32(buf + 1), 0xFEDCBA98u);
    CHECK_EQ_U(read_le32(buf + 1), 0x98BADCFEu);
    CHECK_EQ_U(read_be32(buf + 5), 0x80010203u);
    CHECK_EQ_U(read_le32(buf + 7), 0xFF040302u);
    write_be16(buf + 3, 0xA55A);
    CHECK_EQ_U(buf[3], 0xA5);
    CHECK_EQ_U(buf[4], 0x5A);
    write_be32(buf + 1, 0x89ABCDEFu);
    CHECK_EQ_U(read_be32(buf + 1), 0x89ABCDEFu);
    CHECK_EQ_U(buf[1], 0x89);
    write_le32(buf + 6, 0xDEADBEEFu);
    CHECK_EQ_U(buf[6], 0xEF);
    CHECK_EQ_U(buf[9], 0xDE);
    CHECK_EQ_U(read_le32(buf + 6), 0xDEADBEEFu);
    CHECK_EQ_U(buf[0], 0x00);
    CHECK_EQ_U(buf[10], 0xFF);
    return OGE_REPORT();
}
