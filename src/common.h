/* SPDX-License-Identifier: GPL-2.0 */
/*
 * common.h - Structures and constants shared between the XDP/eBPF kernel
 * program (xdp_ddos.bpf.c) and the user-space loader/monitor
 * (xdp_ddos_loader.c).
 *
 * Keeping these definitions in one header guarantees the kernel and user
 * space agree on the exact memory layout of every BPF map value.
 */
#ifndef __COMMON_H
#define __COMMON_H

/* Maximum number of distinct source IPs we track at once. This is an LRU
 * map, so once it is full the least-recently-seen entries are evicted. */
#define MAX_TRACKED_IPS 1048576

/* --- Default detection parameters (overridable from user space) --------- */

/* A "window" is the sliding time bucket over which we count packets.       */
#define DEFAULT_WINDOW_NS      1000000000ULL   /* 1 second                  */

/* If a single source IP sends more than this many packets inside one
 * window, we treat it as a flood and start dropping its traffic.          */
#define DEFAULT_PKT_THRESHOLD  2000ULL

/* SYN flood is detected separately with a lower threshold, because a burst
 * of half-open connections is cheap to send but expensive to absorb.      */
#define DEFAULT_SYN_THRESHOLD  200ULL

/* Once an IP is flagged, drop everything from it for this long.           */
#define DEFAULT_BLOCK_NS       (30ULL * 1000000000ULL) /* 30 seconds       */

/* Indices into the global statistics array map (stats_map). */
enum stat_index {
	STAT_TOTAL_PKTS = 0, /* every packet the XDP hook saw          */
	STAT_PASSED_PKTS,    /* packets allowed through (XDP_PASS)     */
	STAT_DROPPED_PKTS,   /* packets dropped as attack (XDP_DROP)   */
	STAT_TCP_PKTS,
	STAT_UDP_PKTS,
	STAT_ICMP_PKTS,
	STAT_SYN_PKTS,       /* TCP SYN (no ACK) packets seen          */
	STAT_BLOCK_EVENTS,   /* number of times an IP got newly blocked */
	__STAT_MAX,
};

/* Per-source-IP tracking state stored in ip_track_map. */
struct ip_stats {
	__u64 window_start;   /* start of the current counting window (ns) */
	__u64 packets;        /* packets from this IP in the current window */
	__u64 syn_count;      /* SYN packets from this IP in current window */
	__u64 total_packets;  /* total packets ever seen from this IP       */
	__u64 block_until;    /* if blocked, ns timestamp block expires at  */
	__u32 blocked;        /* 1 while this IP is actively being dropped  */
	__u32 pad;
};

/* Runtime-tunable configuration pushed from user space into config_map. */
struct config {
	__u64 window_ns;
	__u64 pkt_threshold;
	__u64 syn_threshold;
	__u64 block_ns;
};

#endif /* __COMMON_H */
