#include "task.h"

int ccsds_parse_primary(const uint8_t *buf, size_t len, ccsds_primary_header_t *hdr)
{
    if (buf == NULL || hdr == NULL || len < 6u) {
        return -1;
    }
    uint16_t w0 = (uint16_t)(((uint16_t)buf[0] << 8) | buf[1]);
    uint16_t w1 = (uint16_t)(((uint16_t)buf[2] << 8) | buf[3]);
    hdr->version = (uint8_t)(w0 >> 13);
    hdr->type = (uint8_t)((w0 >> 12) & 1u);
    hdr->sec_hdr = (uint8_t)((w0 >> 11) & 1u);
    hdr->apid = (uint16_t)(w0 & 0x7FFu);
    hdr->seq_flags = (uint8_t)(w1 >> 14);
    hdr->seq_count = (uint16_t)(w1 & 0x3FFFu);
    hdr->data_length = (uint16_t)(((uint16_t)buf[4] << 8) | buf[5]);
    return hdr->version == 0u ? 0 : -2;
}

size_t ccsds_packet_length(const ccsds_primary_header_t *hdr) { return 6u + (size_t)hdr->data_length + 1u; }

int ccsds_build_primary(const ccsds_primary_header_t *hdr, uint8_t out[6])
{
    if (hdr->version > 7u || hdr->type > 1u || hdr->sec_hdr > 1u || hdr->apid > 2047u ||
        hdr->seq_flags > 3u || hdr->seq_count > 16383u) {
        return -1;
    }
    uint16_t w0 = (uint16_t)((hdr->version << 13) | (hdr->type << 12) | (hdr->sec_hdr << 11) | hdr->apid);
    uint16_t w1 = (uint16_t)((hdr->seq_flags << 14) | hdr->seq_count);
    out[0] = (uint8_t)(w0 >> 8);
    out[1] = (uint8_t)w0;
    out[2] = (uint8_t)(w1 >> 8);
    out[3] = (uint8_t)w1;
    out[4] = (uint8_t)(hdr->data_length >> 8);
    out[5] = (uint8_t)hdr->data_length;
    return 0;
}
