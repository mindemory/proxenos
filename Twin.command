#!/bin/zsh
# Double-click to open the twin's page. Leave this window open while you use it.
cd "${0:A:h}"
source /opt/anaconda3/etc/profile.d/conda.sh
conda activate digital_twin
twin web
