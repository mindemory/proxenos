#!/bin/zsh
# Double-click to open Proxenos. Leave this window open while you use it.
cd "${0:A:h}"
source /opt/anaconda3/etc/profile.d/conda.sh
# The conda env is "proxenos"; one set up before the rename still has its old name.
conda activate proxenos 2>/dev/null || conda activate digital_twin
proxenos web
