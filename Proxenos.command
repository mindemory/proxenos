#!/bin/zsh
# Double-click to open Proxenos. Leave this window open while you use it.
cd "${0:A:h}"
# The conda env from the README's Quick start, in whichever conda install has it.
for base in ${CONDA_EXE:h:h} ~/miniforge3 ~/miniconda3 ~/anaconda3 /opt/homebrew/Caskroom/miniforge/base /opt/miniconda3 /opt/anaconda3; do
  if [[ -d $base/envs/proxenos && -f $base/etc/profile.d/conda.sh ]]; then
    source $base/etc/profile.d/conda.sh && conda activate proxenos
    break
  fi
done
command -v proxenos >/dev/null || { echo "Proxenos isn't installed yet: see the Quick start in README.md."; exit 1; }
proxenos web
