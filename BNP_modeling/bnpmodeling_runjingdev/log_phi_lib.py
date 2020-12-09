# this just contains a suite of possible functional perturbations 

import jax.numpy as np
import jax.scipy as sp

import bnpmodeling_runjingdev.functional_sensitivity_lib as func_sens_lib
from bnpmodeling_runjingdev import influence_lib

def sigmoidal(logit_v): 
        return (sp.special.expit(logit_v) * 2 - 1.) 

def sigmoidal_neg(logit_v): 
    return (sp.special.expit(-logit_v) * 2 - 1.) 

def alpha_pert_pos(logit_v, alpha0): 
    v = sp.special.expit(logit_v)

    alpha1 = alpha0 + 5.

    return sp.stats.beta.logpdf(v, a = 1, b = alpha1) - sp.stats.beta.logpdf(v, a = 1, b = alpha0)

def alpha_pert_neg(logit_v, alpha0): 
    v = sp.special.expit(logit_v)

    alpha1 = alpha0 - 5.

    return sp.stats.beta.logpdf(v, a = 1, b = alpha1) - sp.stats.beta.logpdf(v, a = 1, b = alpha0)

class LogPhiPerturbations(): 
    def __init__(self, 
                 vb_params_paragami, 
                 alpha0,
                 gh_loc, 
                 gh_weights,
                 logit_v_grid = None, 
                 influence_grid = None, 
                 stick_key = 'stick_params'): 
        
        ##############
        # Sigmoidal perturbations
        ##############
        self.f_obj_sigmoidal = func_sens_lib.FunctionalPerturbationObjective(sigmoidal, 
                                                     vb_params_paragami, 
                                                     gh_loc, 
                                                     gh_weights, 
                                                     stick_key = stick_key)
        
        self.f_obj_sigmoidal_neg = func_sens_lib.FunctionalPerturbationObjective(sigmoidal_neg, 
                                                     vb_params_paragami, 
                                                     gh_loc, 
                                                     gh_weights, 
                                                     stick_key = stick_key)
        
        ##############
        # alpha-type perturbations
        ##############
        self.f_obj_alpha_pert_pos = \
            func_sens_lib.FunctionalPerturbationObjective(lambda x : alpha_pert_pos(x, alpha0),
                                                     vb_params_paragami, 
                                                     gh_loc, 
                                                     gh_weights, 
                                                     stick_key = stick_key)
        
        self.f_obj_alpha_pert_neg = \
            func_sens_lib.FunctionalPerturbationObjective(lambda x : alpha_pert_neg(x, alpha0),
                                                     vb_params_paragami, 
                                                     gh_loc, 
                                                     gh_weights, 
                                                     stick_key = stick_key)
        
        ##############
        # Worst-case perturbation
        ##############
        if influence_grid is not None: 
            worst_case_pert = \
                influence_lib.WorstCasePerturbation(influence_fun = None, 
                                                    logit_v_grid = logit_v_grid, 
                                                    cached_influence_grid = influence_grid)
            
            # interpolate influence function w step functions
            def influence_fun_interp(logit_v): 
                # find index of logit_v_grid 
                # closest (on the left) to logit_v
                indx = np.searchsorted(worst_case_pert.logit_v_grid, logit_v)

                # return the influence function at those points
                return worst_case_pert.influence_grid[indx]

            # define log phi
            def log_phi(logit_v):
                return(np.sign(influence_fun_interp(logit_v)) * worst_case_pert.delta)

        
            self.f_obj_worst_case = \
                func_sens_lib.FunctionalPerturbationObjective(log_phi, 
                                                         vb_params_paragami, 
                                                         gh_loc, 
                                                         gh_weights, 
                                                         e_log_phi = worst_case_pert.get_e_log_linf_perturbation, 
                                                         stick_key = stick_key)