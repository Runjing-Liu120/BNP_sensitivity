#!/bin/bash

source activate genomic_time_series_py35

seed=345345

nobs=50
nloci=40
npop=4

alpha=5.0

/usr/bin/env python3 ./get_structure_fit.py \
  --seed ${seed} \
  --data_file ../data/simulated_structure_data__nobs${nobs}_nloci${nloci}_npop${npop} \
  --outfolder ../fits/\
  --out_filename testing
  # --outfolder /scratch/users/genomic_times_series_bnp/structure_fits/ \
  # --out_filename structure_fit_nobs${nobs}_nloci${nloci}_npop${npop}_alpha${alpha}
