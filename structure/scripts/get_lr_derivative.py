import jax

import jax.numpy as np
import jax.scipy as sp

from structure_vb_lib import structure_model_lib
from structure_vb_lib.preconditioner_lib import get_mfvb_cov_matmul
import structure_vb_lib.structure_optimization_lib as s_optim_lib

import bnpmodeling_runjingdev.functional_sensitivity_lib as func_sens_lib
import bnpmodeling_runjingdev.exponential_families as ef
from bnpmodeling_runjingdev import influence_lib, log_phi_lib

from bnpmodeling_runjingdev.sensitivity_lib import \
        HyperparameterSensitivityLinearApproximation

import paragami

from copy import deepcopy

import time

import re
import os
import argparse
parser = argparse.ArgumentParser()

# the genome dataset
parser.add_argument('--data_file', type=str)

# folder where the structure fit was saved
parser.add_argument('--out_folder', type=str)

# name of the structure fit 
parser.add_argument('--fit_file', type=str)

# tolerance of CG solver
parser.add_argument('--cg_tol', type=float, default=1e-2)

args = parser.parse_args()

fit_file = os.path.join(args.out_folder, args.fit_file)

def validate_args():
    assert os.path.exists(args.out_folder), args.out_folder
    assert os.path.isfile(args.data_file), args.data_file
    
    assert args.fit_file.endswith('.npz')
    assert os.path.isfile(fit_file), fit_file


validate_args()

outfile = re.sub('.npz', '_lrderivatives', fit_file)
print('derivative outfile: ', outfile)

##################
# Load data
##################
print('loading data from ', args.data_file)
data = np.load(args.data_file)
g_obs = np.array(data['g_obs'])

##################
# Load initial fit
##################
print('loading fit from ', fit_file)
vb_opt_dict, vb_params_paragami, \
    prior_params_dict, prior_params_paragami, \
        gh_loc, gh_weights, meta_data = \
            structure_model_lib.load_structure_fit(fit_file)

vb_opt = vb_params_paragami.flatten(vb_opt_dict, free = True)

###############
# Define objective and check KL
###############
# this also contains the hvp
stru_objective = s_optim_lib.StructureObjective(g_obs, 
                                                vb_params_paragami,
                                                prior_params_dict, 
                                                gh_loc, gh_weights, 
                                                jit_functions = False)

# check KL's match
kl = stru_objective.f(vb_opt)
diff = np.abs(kl - meta_data['final_kl'])
assert diff < 1e-8, diff

###############
# Define preconditioner
###############
cg_precond = lambda v : get_mfvb_cov_matmul(v, vb_opt_dict,
                                            vb_params_paragami,
                                            return_sqrt = False, 
                                            return_info = True)

###############
# Derivative wrt to dp prior alpha
###############
print('###############')
print('Computing alpha derivative ...')
print('###############')

# the hyper parameter objective function
alpha0 = prior_params_dict['dp_prior_alpha']
alpha_free = prior_params_paragami['dp_prior_alpha'].flatten(alpha0, 
                                                              free = True)

def alpha_obj_fun(vb_params_free, epsilon): 
    
    # fold free parameters
    vb_params_dict = vb_params_paragami.fold(vb_params_free, 
                                                free = True)
    
    alpha = prior_params_paragami['dp_prior_alpha'].fold(alpha_free + epsilon, 
                                                         free = True)
    
    # return objective
    return structure_model_lib.alpha_objective_fun(vb_params_dict, 
                                                    alpha, 
                                                    gh_loc, 
                                                    gh_weights)
    

# Define the linear sensitivity class
vb_sens = HyperparameterSensitivityLinearApproximation(
                    objective_fun = stru_objective.f, 
                    opt_par_value = vb_opt, 
                    hyper_par_value0 = np.array([0.]), 
                    obj_fun_hvp = stru_objective.hvp, 
                    hyper_par_objective_fun = alpha_obj_fun, 
                    cg_precond = cg_precond, 
                    cg_tol = args.cg_tol,
                    cg_maxiter = None)

print('cg tol: ')
print(vb_sens.cg_tol)
print(vb_sens.cg_maxiter)

# save what we need
vars_to_save = dict()
vars_to_save['dinput_dalpha'] = deepcopy(vb_sens.dinput_dhyper)
vars_to_save['lr_time_alpha'] = deepcopy(vb_sens.lr_time)

def save_derivatives(vars_to_save): 
    print('saving into: ', outfile)
    np.savez(outfile,
             vb_opt = vb_opt,
             dp_prior_alpha = alpha0,
             kl= kl,
             cg_tol = vb_sens.cg_tol,
             cg_maxiter = vb_sens.cg_maxiter,
             **vars_to_save)

save_derivatives(vars_to_save)

    
###############
# Compute influence function
###############
# print('###############')
# print('Computing influence function ...')
# print('###############')

# # posterior expected number of clusters 
# def g(vb_free_params, vb_params_paragami): 
    
#     # key for random sampling. 
#     # this is fixed! so all standard normal 
#     # samples used in computing the posterior quantity 
#     key = jax.random.PRNGKey(0)
    
#     vb_params_dict = vb_params_paragami.fold(vb_free_params, free = True)
    
#     stick_means = vb_params_dict['ind_admix_params']['stick_means']
#     stick_infos = vb_params_dict['ind_admix_params']['stick_infos']
    
#     return structure_model_lib.get_e_num_pred_clusters(stick_means, stick_infos, gh_loc, gh_weights, 
#                                                        key = key,
#                                                        n_samples = 100)

# get_grad_g = jax.jacobian(g, argnums = 0)
# grad_g = get_grad_g(vb_opt, vb_params_paragami)

# # get influence function
# print('computing influence function...')
# influence_operator = influence_lib.InfluenceOperator(vb_opt, 
#                            vb_params_paragami, 
#                            vb_sens.hessian_solver,
#                            prior_params_dict['dp_prior_alpha'], 
#                            stick_key = 'ind_admix_params')

# logit_v_grid = np.linspace(-10, 10, 200)
# influence_grid = influence_operator.get_influence(logit_v_grid, grad_g)

# # save what we need
# vars_to_save['logit_v_grid'] = logit_v_grid
# vars_to_save['influence_grid'] = influence_grid
# save_derivatives(vars_to_save)


###############
# Derivative wrt to functional perturbations
###############
f_obj_all = log_phi_lib.LogPhiPerturbations(vb_params_paragami, 
                                            prior_params_dict['dp_prior_alpha'],
                                            gh_loc, 
                                            gh_weights,
                                            # logit_v_grid = logit_v_grid, 
                                            # influence_grid = influence_grid, 
                                            stick_key = 'ind_admix_params')

def compute_derivatives_and_save(pert_name):
    
    print('###############')
    print('Computing derviative for ' + pert_name + ' functional perturbation ...')
    print('###############')

    
    # get hyper parameter objective function
    f_obj = getattr(f_obj_all, 'f_obj_' + pert_name)
    
    # compute derivative 
    print('computing derivative...')
    vb_sens._set_cross_hess_and_solve(f_obj.hyper_par_objective_fun)
    
    # save what we need
    vars_to_save['dinput_dfun_' + pert_name] = deepcopy(vb_sens.dinput_dhyper)
    vars_to_save['lr_time_' + pert_name] = deepcopy(vb_sens.lr_time)
    save_derivatives(vars_to_save)

# compute_derivatives_and_save('worst_case')

compute_derivatives_and_save('sigmoidal')

compute_derivatives_and_save('alpha_pert_pos')
compute_derivatives_and_save('alpha_pert_neg')

compute_derivatives_and_save('alpha_pert_pos_xflip')
compute_derivatives_and_save('alpha_pert_neg_xflip')

compute_derivatives_and_save('gauss_pert1')
compute_derivatives_and_save('gauss_pert2')


print('done. ')
