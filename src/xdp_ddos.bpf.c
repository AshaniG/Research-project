/* SPDX-License-Identifier: GPL-2.0 */
/*
 * xdp_ddos.bpf.c - Kernel-level DDoS detection with XDP/eBPF.
 *
 * This program is attached to a network interface at the XDP hook, which is
 * the earliest point in the receive path (in the NIC driver, before the
 * kernel allocates an sk_buff). Running here lets us count and drop attack
 * traffic at line rate with minimal CPU cost.
 *
 * Detection strategy (per source IPv4 address):
 *   - Count packets inside a sliding time window.
 *   - Count TCP SYN packets separately (SYN-flood signal).
 *   - If either count crosses its threshold, mark the source as "blocked"
 *     and XDP_DROP all of its packets for a cool-down period.
 *
 * Everything else is passed up the stack unchanged (XDP_PASS).
 */
#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/tcp.h>
#include <linux/udp.h>
#include <linux/in.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>
#include "common.h"

char LICENSE[] SEC("license") = "GPL";

/* Per-source-IP state. LRU so a flood of spoofed IPs cannot exhaust it. */
struct {
	__uint(type, BPF_MAP_TYPE_LRU_HASH);
	__uint(max_entries, MAX_TRACKED_IPS);
	__type(key, __u32);            /* source IPv4 address (network order) */
	__type(value, struct ip_stats);
} ip_track_map SEC(".maps");

/* Global counters, indexed by enum stat_index. */
struct {
	__uint(type, BPF_MAP_TYPE_ARRAY);
	__uint(max_entries, __STAT_MAX);
	__type(key, __u32);
	__type(value, __u64);
} stats_map SEC(".maps");

/* Single-entry config map, populated by the user-space loader. */
struct {
	__uint(type, BPF_MAP_TYPE_ARRAY);
	__uint(max_entries, 1);
	__type(key, __u32);
	__type(value, struct config);
} config_map SEC(".maps");

static __always_inline void incr_stat(__u32 idx)
{
	__u64 *val = bpf_map_lookup_elem(&stats_map, &idx);
	if (val)
		__sync_fetch_and_add(val, 1);
}

SEC("xdp")
int xdp_ddos_detect(struct xdp_md *ctx)
{
	void *data = (void *)(long)ctx->data;
	void *data_end = (void *)(long)ctx->data_end;

	incr_stat(STAT_TOTAL_PKTS);

	/* --- Parse Ethernet ------------------------------------------------ */
	struct ethhdr *eth = data;
	if ((void *)(eth + 1) > data_end)
		return XDP_PASS;

	/* Only IPv4 is inspected; let everything else through untouched. */
	if (eth->h_proto != bpf_htons(ETH_P_IP))
		return XDP_PASS;

	/* --- Parse IPv4 ---------------------------------------------------- */
	struct iphdr *ip = (void *)(eth + 1);
	if ((void *)(ip + 1) > data_end)
		return XDP_PASS;

	/* IHL is in 32-bit words; a valid IPv4 header is at least 20 bytes. */
	if (ip->ihl < 5)
		return XDP_PASS;
	__u32 ihl_bytes = ip->ihl * 4;

	__u32 src_ip = ip->saddr;
	__u8 proto = ip->protocol;
	__u64 now = bpf_ktime_get_ns();

	/* --- Load runtime config (fall back to compile-time defaults) ------ */
	__u32 czero = 0;
	struct config *cfg = bpf_map_lookup_elem(&config_map, &czero);
	__u64 window_ns = DEFAULT_WINDOW_NS;
	__u64 pkt_threshold = DEFAULT_PKT_THRESHOLD;
	__u64 syn_threshold = DEFAULT_SYN_THRESHOLD;
	__u64 block_ns = DEFAULT_BLOCK_NS;
	if (cfg && cfg->window_ns) {
		window_ns = cfg->window_ns;
		pkt_threshold = cfg->pkt_threshold;
		syn_threshold = cfg->syn_threshold;
		block_ns = cfg->block_ns;
	}

	/* --- Per-protocol accounting + SYN detection ----------------------- */
	int is_syn = 0;
	if (proto == IPPROTO_TCP) {
		incr_stat(STAT_TCP_PKTS);
		struct tcphdr *tcp = (void *)ip + ihl_bytes;
		if ((void *)(tcp + 1) > data_end)
			return XDP_PASS;
		/* A SYN without ACK is a connection-open attempt. */
		if (tcp->syn && !tcp->ack) {
			is_syn = 1;
			incr_stat(STAT_SYN_PKTS);
		}
	} else if (proto == IPPROTO_UDP) {
		incr_stat(STAT_UDP_PKTS);
	} else if (proto == IPPROTO_ICMP) {
		incr_stat(STAT_ICMP_PKTS);
	}

	/* --- Rate tracking -------------------------------------------------- */
	struct ip_stats *st = bpf_map_lookup_elem(&ip_track_map, &src_ip);
	if (!st) {
		/* First time we see this source: create its entry and pass. */
		struct ip_stats fresh = {};
		fresh.window_start = now;
		fresh.packets = 1;
		fresh.total_packets = 1;
		fresh.syn_count = is_syn ? 1 : 0;
		bpf_map_update_elem(&ip_track_map, &src_ip, &fresh, BPF_ANY);
		incr_stat(STAT_PASSED_PKTS);
		return XDP_PASS;
	}

	/* If this IP is in a block period, drop until it expires. */
	if (st->blocked) {
		if (now < st->block_until) {
			incr_stat(STAT_DROPPED_PKTS);
			return XDP_DROP;
		}
		/* Cool-down elapsed: give the source a clean slate. */
		st->blocked = 0;
		st->packets = 0;
		st->syn_count = 0;
		st->window_start = now;
	}

	/* Roll the counting window if it has elapsed. */
	if (now - st->window_start > window_ns) {
		st->window_start = now;
		st->packets = 0;
		st->syn_count = 0;
	}

	st->packets++;
	st->total_packets++;
	if (is_syn)
		st->syn_count++;

	/* --- Decision ------------------------------------------------------ */
	if (st->packets > pkt_threshold || st->syn_count > syn_threshold) {
		st->blocked = 1;
		st->block_until = now + block_ns;
		incr_stat(STAT_DROPPED_PKTS);
		incr_stat(STAT_BLOCK_EVENTS);
		return XDP_DROP;
	}

	incr_stat(STAT_PASSED_PKTS);
	return XDP_PASS;
}
