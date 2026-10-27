#ifndef TASK_H
#define TASK_H
#include <stddef.h>
#include <stdint.h>

/* Primary header, big-endian bit fields in this order:
   version (3 bits) | type (1) | secondary header flag (1) | APID (11) |
   sequence flags (2) | sequence count (14) | packet data length (16).
   data_length is the length of the packet data field minus 1. */
typedef struct {
    uint8_t version;
    uint8_t type;
    uint8_t sec_hdr;
    uint16_t apid;
    uint8_t seq_flags;
    uint16_t seq_count;
    uint16_t data_length;
} ccsds_primary_header_t;

/* Returns 0 on success, -1 if buf or hdr is NULL or len < 6, -2 if the version field is not 0. */
int ccsds_parse_primary(const uint8_t *buf, size_t len, ccsds_primary_header_t *hdr);

/* Total packet length in bytes: 6 + data_length + 1. */
size_t ccsds_packet_length(const ccsds_primary_header_t *hdr);

/* Serialises hdr into out[0..6). Returns 0, or -1 if any field exceeds its bit width
   (version > 7, type > 1, sec_hdr > 1, apid > 2047, seq_flags > 3, seq_count > 16383). */
int ccsds_build_primary(const ccsds_primary_header_t *hdr, uint8_t out[6]);

#endif
