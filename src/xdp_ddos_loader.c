// SPDX-License-Identifier: GPL-2.0
/*
 * xdp_ddos_loader.c - User-space loader and live monitor for the XDP/eBPF
 * DDoS detector.
 *
 * Responsibilities:
 *   1. Load the compiled BPF object (build/xdp_ddos.bpf.o).
 *   2. Push runtime configuration (thresholds) into config_map.
 *   3. Attach the XDP program to the chosen network interface.
 *   4. Poll the stats and per-IP maps once per second and render a live
 *      dashboard, including the currently blocked source IPs.
 *   5. Detach cleanly on Ctrl-C.
 *
 * Build with the top-level Makefile; run as root (XDP attach needs
 * CAP_NET_ADMIN / CAP_BPF).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include <errno.h>
#include <getopt.h>
#include <time.h>
#include <net/if.h>
#include <arpa/inet.h>
#include <linux/if_link.h>

#include <bpf/libbpf.h>
#include <bpf/bpf.h>

#include "common.h"

static volatile sig_atomic_t stop;
static int ifindex = -1;
static struct bpf_link *xdp_link;

static void on_signal(int sig)
{
	(void)sig;
	stop = 1;
}

static const char *stat_names[__STAT_MAX] = {
	[STAT_TOTAL_PKTS]   = "Total packets seen",
	[STAT_PASSED_PKTS]  = "Passed (allowed)",
	[STAT_DROPPED_PKTS] = "Dropped (attack)",
	[STAT_TCP_PKTS]     = "TCP packets",
	[STAT_UDP_PKTS]     = "UDP packets",
	[STAT_ICMP_PKTS]    = "ICMP packets",
	[STAT_SYN_PKTS]     = "TCP SYN packets",
	[STAT_BLOCK_EVENTS] = "IP block events",
};

/* Walk ip_track_map and print any source IPs currently in the blocked state. */
static void print_blocked_ips(int map_fd)
{
	__u32 key = 0, next_key;
	struct ip_stats val;
	int shown = 0;

	printf("\n Currently blocked sources (src IP  ->  total pkts):\n");

	/* Iterate from the very first key. bpf_map_get_next_key(fd, NULL, &k)
	 * returns the first key when the "prev" pointer is NULL. */
	int ret = bpf_map_get_next_key(map_fd, NULL, &next_key);
	while (ret == 0) {
		key = next_key;
		if (bpf_map_lookup_elem(map_fd, &key, &val) == 0 && val.blocked) {
			struct in_addr a = { .s_addr = key };
			printf("   %-16s  %llu pkts (%llu SYN)\n",
			       inet_ntoa(a),
			       (unsigned long long)val.total_packets,
			       (unsigned long long)val.syn_count);
			shown++;
			if (shown >= 20) {
				printf("   ... (showing first 20)\n");
				break;
			}
		}
		ret = bpf_map_get_next_key(map_fd, &key, &next_key);
	}
	if (!shown)
		printf("   (none)\n");
}

static void usage(const char *prog)
{
	fprintf(stderr,
		"Kernel-level DDoS detector (XDP/eBPF)\n\n"
		"Usage: sudo %s -i <iface> [options]\n\n"
		"  -i, --iface <name>     interface to protect (required, e.g. eth0)\n"
		"  -p, --pkt <n>          packets/window before an IP is blocked (default %llu)\n"
		"  -s, --syn <n>          SYN packets/window before block (default %llu)\n"
		"  -w, --window <ms>      window length in milliseconds (default 1000)\n"
		"  -b, --block <sec>      block duration in seconds (default 30)\n"
		"  -S, --skb              use SKB (generic) mode instead of native XDP\n"
		"  -h, --help             show this help\n",
		prog,
		(unsigned long long)DEFAULT_PKT_THRESHOLD,
		(unsigned long long)DEFAULT_SYN_THRESHOLD);
}

int main(int argc, char **argv)
{
	const char *iface = NULL;
	struct config cfg = {
		.window_ns = DEFAULT_WINDOW_NS,
		.pkt_threshold = DEFAULT_PKT_THRESHOLD,
		.syn_threshold = DEFAULT_SYN_THRESHOLD,
		.block_ns = DEFAULT_BLOCK_NS,
	};
	__u32 xdp_flags = XDP_FLAGS_DRV_MODE; /* native/driver mode by default */

	static struct option long_opts[] = {
		{ "iface",  required_argument, 0, 'i' },
		{ "pkt",    required_argument, 0, 'p' },
		{ "syn",    required_argument, 0, 's' },
		{ "window", required_argument, 0, 'w' },
		{ "block",  required_argument, 0, 'b' },
		{ "skb",    no_argument,       0, 'S' },
		{ "help",   no_argument,       0, 'h' },
		{ 0, 0, 0, 0 }
	};
	int opt;
	while ((opt = getopt_long(argc, argv, "i:p:s:w:b:Sh", long_opts, NULL)) != -1) {
		switch (opt) {
		case 'i': iface = optarg; break;
		case 'p': cfg.pkt_threshold = strtoull(optarg, NULL, 10); break;
		case 's': cfg.syn_threshold = strtoull(optarg, NULL, 10); break;
		case 'w': cfg.window_ns = strtoull(optarg, NULL, 10) * 1000000ULL; break;
		case 'b': cfg.block_ns = strtoull(optarg, NULL, 10) * 1000000000ULL; break;
		case 'S': xdp_flags = XDP_FLAGS_SKB_MODE; break;
		case 'h': usage(argv[0]); return 0;
		default:  usage(argv[0]); return 1;
		}
	}

	if (!iface) {
		usage(argv[0]);
		return 1;
	}

	ifindex = if_nametoindex(iface);
	if (!ifindex) {
		fprintf(stderr, "error: unknown interface '%s': %s\n",
			iface, strerror(errno));
		return 1;
	}

	signal(SIGINT, on_signal);
	signal(SIGTERM, on_signal);

	/* --- Load the BPF object ------------------------------------------ */
	struct bpf_object *obj = bpf_object__open_file("build/xdp_ddos.bpf.o", NULL);
	if (!obj || libbpf_get_error(obj)) {
		fprintf(stderr, "error: failed to open build/xdp_ddos.bpf.o "
			"(did you run 'make'?)\n");
		return 1;
	}

	if (bpf_object__load(obj)) {
		fprintf(stderr, "error: failed to load BPF object into kernel: %s\n",
			strerror(errno));
		bpf_object__close(obj);
		return 1;
	}

	int stats_fd = bpf_object__find_map_fd_by_name(obj, "stats_map");
	int track_fd = bpf_object__find_map_fd_by_name(obj, "ip_track_map");
	int cfg_fd   = bpf_object__find_map_fd_by_name(obj, "config_map");
	if (stats_fd < 0 || track_fd < 0 || cfg_fd < 0) {
		fprintf(stderr, "error: could not find expected BPF maps\n");
		bpf_object__close(obj);
		return 1;
	}

	/* Push configuration into the kernel. */
	__u32 czero = 0;
	if (bpf_map_update_elem(cfg_fd, &czero, &cfg, BPF_ANY)) {
		fprintf(stderr, "error: failed to write config map: %s\n",
			strerror(errno));
		bpf_object__close(obj);
		return 1;
	}

	/* --- Attach XDP ---------------------------------------------------- */
	struct bpf_program *prog =
		bpf_object__find_program_by_name(obj, "xdp_ddos_detect");
	if (!prog) {
		fprintf(stderr, "error: program xdp_ddos_detect not found\n");
		bpf_object__close(obj);
		return 1;
	}

	xdp_link = bpf_program__attach_xdp(prog, ifindex);
	if (libbpf_get_error(xdp_link)) {
		/* Native mode may be unsupported by the driver/veth; retry SKB. */
		fprintf(stderr, "warning: native XDP attach failed, "
			"retrying in SKB (generic) mode...\n");
		xdp_link = NULL;
		LIBBPF_OPTS(bpf_xdp_attach_opts, aopts);
		int prog_fd = bpf_program__fd(prog);
		if (bpf_xdp_attach(ifindex, prog_fd, XDP_FLAGS_SKB_MODE, &aopts)) {
			fprintf(stderr, "error: XDP attach failed on '%s': %s\n",
				iface, strerror(errno));
			bpf_object__close(obj);
			return 1;
		}
		xdp_flags = XDP_FLAGS_SKB_MODE;
	} else {
		(void)xdp_flags;
	}

	printf("XDP DDoS detector attached to %s (ifindex %d)\n", iface, ifindex);
	printf("Thresholds: %llu pkts/win, %llu SYN/win, window %llu ms, block %llu s\n",
	       (unsigned long long)cfg.pkt_threshold,
	       (unsigned long long)cfg.syn_threshold,
	       (unsigned long long)(cfg.window_ns / 1000000ULL),
	       (unsigned long long)(cfg.block_ns / 1000000000ULL));
	printf("Press Ctrl-C to detach.\n");

	/* --- Live monitor loop --------------------------------------------- */
	__u64 prev_total = 0;
	while (!stop) {
		sleep(1);

		__u64 stats[__STAT_MAX] = {0};
		for (__u32 i = 0; i < __STAT_MAX; i++)
			bpf_map_lookup_elem(stats_fd, &i, &stats[i]);

		__u64 pps = stats[STAT_TOTAL_PKTS] - prev_total;
		prev_total = stats[STAT_TOTAL_PKTS];

		printf("\033[2J\033[H"); /* clear screen, cursor home */
		time_t t = time(NULL);
		char ts[32];
		strftime(ts, sizeof(ts), "%H:%M:%S", localtime(&t));
		printf("=== XDP DDoS Detector on %s ===   %s   %llu pps\n\n",
		       iface, ts, (unsigned long long)pps);

		for (__u32 i = 0; i < __STAT_MAX; i++)
			printf(" %-22s : %llu\n",
			       stat_names[i] ? stat_names[i] : "?",
			       (unsigned long long)stats[i]);

		print_blocked_ips(track_fd);
		fflush(stdout);
	}

	/* --- Detach and clean up ------------------------------------------- */
	printf("\nDetaching...\n");
	if (xdp_link)
		bpf_link__destroy(xdp_link);
	else
		bpf_xdp_detach(ifindex, XDP_FLAGS_SKB_MODE, NULL);
	bpf_object__close(obj);
	printf("Done.\n");
	return 0;
}
