#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-only
"""Publish only sanitized NVMe health metrics to the root-owned runtime cache."""
import ssd_health
if __name__=='__main__':ssd_health.export()
