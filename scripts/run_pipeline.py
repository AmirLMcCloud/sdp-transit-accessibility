#!/usr/bin/env python
"""Convenience wrapper: python scripts/run_pipeline.py [data|route|equity|map|all]"""
import sys
from sdp_access.cli import main

main(sys.argv[1:] or ["all"])
