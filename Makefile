# Makefile for the kernel-level DDoS detector (XDP/eBPF).
#
#   make          build the eBPF object and the user-space monitor
#   make clean     remove build artifacts
#
# Requires: clang/llvm, libbpf-dev, libelf, and kernel headers.
# Run scripts/setup.sh first on a fresh machine to install these.

CLANG   ?= clang
CC      ?= gcc

# Map `uname -m` to the arch token clang/bpf expects.
ARCH := $(shell uname -m | sed 's/x86_64/x86/' \
                          | sed 's/aarch64/arm64/' \
                          | sed 's/armv7l/arm/' \
                          | sed 's/ppc64le/powerpc/')

# Multiarch include dir (holds asm/types.h etc.) so BPF compiles cleanly.
TRIPLET := $(shell $(CC) -dumpmachine)

SRC   := src
BUILD := build

BPF_CFLAGS  := -g -O2 -Wall -target bpf -D__TARGET_ARCH_$(ARCH) \
               -I/usr/include/$(TRIPLET)
USER_CFLAGS := -g -O2 -Wall
USER_LIBS   := -lbpf -lelf -lz

.PHONY: all clean

all: $(BUILD)/xdp_ddos.bpf.o $(BUILD)/xdp_ddos_loader

$(BUILD):
	mkdir -p $(BUILD)

# Kernel-space: compile the XDP program to BPF bytecode.
$(BUILD)/xdp_ddos.bpf.o: $(SRC)/xdp_ddos.bpf.c $(SRC)/common.h | $(BUILD)
	$(CLANG) $(BPF_CFLAGS) -c $< -o $@

# User-space: the loader/monitor linked against libbpf.
$(BUILD)/xdp_ddos_loader: $(SRC)/xdp_ddos_loader.c $(SRC)/common.h | $(BUILD)
	$(CC) $(USER_CFLAGS) $< -o $@ $(USER_LIBS)

clean:
	rm -rf $(BUILD)
