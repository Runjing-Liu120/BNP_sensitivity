import jax
from jax import numpy as np
from jax import scipy as sp
from jax import random

from numpy.polynomial.hermite import hermgauss

import time

import os
import argparse
import distutils.util

import paragami

# functional sensitivity library
from bnpmodeling_runjingdev import log_phi_lib

# BNP gmm libraries
# BNP regression mixture libraries
from bnpreg_runjingdev import genomics_data_utils
from bnpreg_runjingdev import regression_mixture_lib
from bnpreg_runjingdev.regression_optimization_lib import optimize_regression_mixture


parser = argparse.ArgumentParser()

parser.add_argument('--seed', type=int, default=42)

# Set bnp_data_repo to be the location of a clone of the repo
# https://github.com/NelleV/genomic_time_series_bnp
parser.add_argument('--bnp_data_repo', type=str, 
                    default = '../../../genomic_time_series_bnp')


# where to save the gmm fit
parser.add_argument('--out_folder', default='../fits/')
parser.add_argument('--out_filename', type=str)

# the initial fit
parser.add_argument('--init_fit', type=str)

# which epsilon 
parser.add_argument('--epsilon_indx', type=int, default = 0)

# delta 
parser.add_argument('--delta', type=float, default = 1.0)

# which perturbation
parser.add_argument('--perturbation', type=str, default = 'sigmoidal')

args = parser.parse_args()

assert os.path.exists(args.out_folder), args.out_folder
assert os.path.isfile(args.init_fit), args.init_fit

########################
# load mice regression data
########################
genome_data, timepoints, regressors, beta, beta_infos, y_infos = \
    genomics_data_utils.load_data_and_run_regressions(args.bnp_data_repo)

n_genes = genome_data.shape[0]
reg_dim = regressors.shape[1]

n_timepoints = len(np.unique(timepoints))

########################
# Variational parameters
########################
vb_init_dict, vb_params_paragami, meta_data = \
        paragami.load_folded(args.init_fit)

# gauss-hermite parameters
gh_deg = int(meta_data['gh_deg'])
gh_loc, gh_weights = hermgauss(gh_deg)

gh_loc = np.array(gh_loc)
gh_weights = np.array(gh_weights)

########################
# load prior parameters
########################
prior_params_dict, prior_params_paragami = \
    regression_mixture_lib.get_default_prior_params()

# set alpha
dp_prior_alpha = meta_data['dp_prior_alpha']
prior_params_dict['dp_prior_alpha'] = dp_prior_alpha

########################
# Functional perturbation 
########################
# set epsilon
epsilon_vec = np.linspace(0, 1, 20)[1:]**2 
epsilon = epsilon_vec[args.epsilon_indx]
print('epsilon = ', epsilon)
print('epsilon_indx = ', args.epsilon_indx)

# define perturbation
f_obj_all = log_phi_lib.LogPhiPerturbations(vb_params_paragami, 
                                            dp_prior_alpha,
                                            gh_loc, 
                                            gh_weights,
                                            delta = args.delta, 
                                            stick_key = 'stick_params')

f_obj = getattr(f_obj_all, 'f_obj_' + args.perturbation)
e_log_phi = lambda means, infos : f_obj.e_log_phi_epsilon(means, infos, epsilon)

########################
# Optimize
########################

vb_opt_dict, vb_opt, ez_opt, out, optim_time = \
    optimize_regression_mixture(genome_data,
                                regressors, 
                                vb_init_dict,
                                vb_params_paragami,
                                prior_params_dict, 
                                gh_loc, 
                                gh_weights, 
                                e_log_phi = e_log_phi, 
                                # directly optimize using newton
                                run_lbfgs = False)

final_kl = out.fun

#####################
# Save results
#####################
outfile = os.path.join(args.out_folder, args.out_filename)
print('saving iris fit to ', outfile)

paragami.save_folded(outfile, 
                     vb_opt_dict,
                     vb_params_paragami, 
                     final_kl = final_kl, 
                     optim_time = optim_time, 
                     gh_deg = gh_deg, 
                     dp_prior_alpha = dp_prior_alpha, 
                     epsilon = epsilon, 
                     delta = args.delta, 
                     perturbation = args.perturbation)

                     