#!/bin/bash

source activate bnp_sensitivity_jax

# all alphas except 6.0 
# 6.0 was the initial fit
alpha_vec=(1.0 1.5 2.0 2.5 3.0 3.5 4.0 4.5 5.0 5.5 \
            6.5 7.0 7.5 8.0 8.5 9.0 9.5 10.0 10.5 11.0)

# pick on alpha
alpha=${alpha_vec[$SLURM_ARRAY_TASK_ID]}

seed=453

python fit_structure.py \
  --seed ${seed} \
  --alpha ${alpha} \
  --data_file ${data_file} \
  --out_folder ${out_folder} \
  --out_filename ${out_filename}_alpha${alpha} \
  --warm_start True \
  --init_fit ${out_folder}${out_filename}_alpha6.0.npz \
  --k_approx 20
