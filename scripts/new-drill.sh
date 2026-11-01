#!/usr/bin/env bash
ID="drill-$(date -u +%Y%m%d-%H%M)-$(openssl rand -hex 2)"
mkdir -p "evidence/$ID" && echo "$ID"
