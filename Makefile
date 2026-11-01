# SPDX-License-Identifier: GPL-2.0-only
PYTHON ?= python3
CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -Werror
KERNEL ?= $(shell uname -r)
KDIR ?= /lib/modules/$(KERNEL)/build
PREFIX ?= /usr/local
BRIDGE ?= $(PREFIX)/lib/asus-healthytable/0.85.0/api_bridge.py

.PHONY: all check module clean install
all: build/libasus-healthytable.so

build:
	mkdir -p build

build/oem-test: source/oem_test.c source/healthytable_oem.h source/healthytable_core.h | build
	$(CC) $(CFLAGS) -std=c11 $< -o $@

build/oem-test-sanitized: source/oem_test.c source/healthytable_oem.h source/healthytable_core.h | build
	$(CC) $(CFLAGS) -std=c11 -O1 -g -fsanitize=address,undefined $< -o $@

build/diagnostics-test: source/diagnostics_test.c source/healthytable_diagnostics.h source/healthytable_telemetry.h source/healthytable_core.h | build
	$(CC) $(CFLAGS) -std=c11 $< -o $@

build/diagnostics-test-sanitized: source/diagnostics_test.c source/healthytable_diagnostics.h source/healthytable_telemetry.h source/healthytable_core.h | build
	$(CC) $(CFLAGS) -std=c11 -O1 -g -fsanitize=address,undefined $< -o $@

build/libasus-healthytable.so: lib/asus_healthytable.c include/asus_healthytable.h Makefile | build
	$(CC) $(CFLAGS) -std=c11 -fPIC -shared -fstack-protector-strong $$($(CC) $(CFLAGS) -dM -E -x c /dev/null | grep -q '_FORTIFY_SOURCE' || echo -D_FORTIFY_SOURCE=2) -Wl,-z,relro,-z,now -Wl,-soname,libasus-healthytable.so.1 -Iinclude -DASUS_HT_BRIDGE='"$(BRIDGE)"' $< -o $@

build/test-libasus-healthytable.so: lib/asus_healthytable.c include/asus_healthytable.h Makefile | build
	$(CC) $(CFLAGS) -std=c11 -fPIC -shared -Iinclude -DASUS_HT_BRIDGE='"$(CURDIR)/api_bridge.py"' $< -o $@

build/sbs-test: source/sbs_test.c source/healthytable_sbs.h source/healthytable_gauge_block.h source/healthytable_gauge.h source/healthytable_charger.h source/healthytable_core.h | build
	$(CC) $(CFLAGS) -std=c11 $< -o $@

build/sbs-test-sanitized: source/sbs_test.c source/healthytable_sbs.h source/healthytable_gauge_block.h source/healthytable_gauge.h source/healthytable_charger.h source/healthytable_core.h | build
	$(CC) $(CFLAGS) -std=c11 -O1 -g -fsanitize=address,undefined $< -o $@

build/pd-identity-test: source/pd_identity_test.c source/healthytable_pd_identity.h source/healthytable_charger.h source/healthytable_core.h | build
	$(CC) $(CFLAGS) -std=c11 $< -o $@

build/pd-identity-test-sanitized: source/pd_identity_test.c source/healthytable_pd_identity.h source/healthytable_charger.h source/healthytable_core.h | build
	$(CC) $(CFLAGS) -std=c11 -O1 -g -fsanitize=address,undefined $< -o $@

build/gauge-test: source/gauge_test.c source/healthytable_gauge.h source/healthytable_core.h | build
	$(CC) $(CFLAGS) -std=c11 $< -o $@

build/gauge-test-sanitized: source/gauge_test.c source/healthytable_gauge.h source/healthytable_core.h | build
	$(CC) $(CFLAGS) -std=c11 -O1 -g -fsanitize=address,undefined $< -o $@

build/gauge-block-test: source/gauge_block_test.c source/healthytable_gauge_block.h source/healthytable_gauge.h source/healthytable_charger.h source/healthytable_core.h | build
	$(CC) $(CFLAGS) -std=c11 $< -o $@

build/gauge-block-test-sanitized: source/gauge_block_test.c source/healthytable_gauge_block.h source/healthytable_gauge.h source/healthytable_charger.h source/healthytable_core.h | build
	$(CC) $(CFLAGS) -std=c11 -O1 -g -fsanitize=address,undefined $< -o $@

build/core-test: source/core_test.c source/healthytable_history.h source/healthytable_telemetry.h source/healthytable_eeprom.h source/healthytable_core.h source/healthytable_oem.h source/healthytable_voltage.h source/healthytable_frequency.h source/healthytable_pd.h source/healthytable_power.h | build
	$(CC) $(CFLAGS) -std=c11 $< -o $@

build/core-test-sanitized: source/core_test.c source/healthytable_history.h source/healthytable_telemetry.h source/healthytable_eeprom.h source/healthytable_core.h source/healthytable_oem.h source/healthytable_voltage.h source/healthytable_frequency.h source/healthytable_pd.h source/healthytable_power.h | build
	$(CC) $(CFLAGS) -std=c11 -O1 -g -fsanitize=address,undefined $< -o $@

build/charger-test: source/charger_test.c source/healthytable_charger.h source/healthytable_core.h | build
	$(CC) $(CFLAGS) -std=c11 $< -o $@

build/charger-test-sanitized: source/charger_test.c source/healthytable_charger.h source/healthytable_core.h | build
	$(CC) $(CFLAGS) -std=c11 -O1 -g -fsanitize=address,undefined $< -o $@

check: build/oem-test build/oem-test-sanitized build/diagnostics-test build/diagnostics-test-sanitized build/sbs-test build/sbs-test-sanitized build/gauge-block-test build/gauge-block-test-sanitized build/pd-identity-test build/pd-identity-test-sanitized build/gauge-test build/gauge-test-sanitized build/charger-test build/charger-test-sanitized all build/test-libasus-healthytable.so build/core-test build/core-test-sanitized
	./build/oem-test
	./build/oem-test-sanitized
	./build/diagnostics-test
	./build/diagnostics-test-sanitized
	./build/sbs-test
	./build/sbs-test-sanitized
	./build/gauge-block-test
	./build/gauge-block-test-sanitized
	./build/pd-identity-test
	./build/pd-identity-test-sanitized
	./build/gauge-test
	./build/gauge-test-sanitized
	./build/charger-test
	./build/charger-test-sanitized
	./build/core-test
	./build/core-test-sanitized
	$(PYTHON) -m unittest discover -v
	$(PYTHON) tools/check-parity.py
	node integrations/vitals/test-charger.js
	node integrations/vitals/test-metrics.js
	node integrations/vitals/test-battery.js
	node integrations/vitals/test-wireless.js
	node integrations/vitals/test-fan.js
	node integrations/vitals/test-frequency.js
	node integrations/vitals/test-service.js
	node gnome-bridge/test-num-lock.mjs
	node gnome-bridge/test-windows.mjs

module:
	$(MAKE) -C $(KDIR) M=$(CURDIR)/source W=1 modules

install: all
	$(PYTHON) tools/install.py

clean:
	rm -rf build __pycache__
	$(MAKE) -C $(KDIR) M=$(CURDIR)/source clean
