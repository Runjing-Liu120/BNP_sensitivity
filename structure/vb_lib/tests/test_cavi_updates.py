import jax

import jax.numpy as np
import jax.scipy as sp

from numpy.polynomial.hermite import hermgauss

from bnpmodeling_runjingdev import modeling_lib

from vb_lib import structure_model_lib, data_utils, cavi_lib

import unittest

# draw data
n_obs = 10
n_loci = 5
n_pop = 3

g_obs = data_utils.draw_data(n_obs, n_loci, n_pop)[0]

# prior parameters
prior_params_dict, prior_params_paragami = \
    structure_model_lib.get_default_prior_params()

dp_prior_alpha = prior_params_dict['dp_prior_alpha']
allele_prior_alpha = prior_params_dict['allele_prior_alpha']
allele_prior_beta = prior_params_dict['allele_prior_beta']

# vb params
k_approx = 12
gh_deg = 8
gh_loc, gh_weights = hermgauss(gh_deg)
use_logitnormal_sticks = False

vb_params_dict, vb_params_paragami = \
    structure_model_lib.\
        get_vb_params_paragami_object(n_obs, 
                                      n_loci,
                                      k_approx,
                                      use_logitnormal_sticks)

# get moments 
e_log_sticks, e_log_1m_sticks, \
    e_log_pop_freq, e_log_1m_pop_freq = \
        structure_model_lib.get_moments_from_vb_params_dict( \
                                vb_params_dict)

e_log_cluster_probs = \
    modeling_lib.get_e_log_cluster_probabilities_from_e_log_stick(
        e_log_sticks, e_log_1m_sticks)

class TestCaviUpdate(unittest.TestCase):

    def test_admixture_stick_update(self):
        
        # closed-form update
        ind_admix_update = cavi_lib.update_ind_admix_beta(g_obs, e_log_pop_freq, e_log_1m_pop_freq, 
                                            e_log_cluster_probs, prior_params_dict)[0]
        
        # autodiff updates
        ind_admix_update1_ag = cavi_lib.get_stick_update1_ag(g_obs,
                        e_log_pop_freq, e_log_1m_pop_freq,
                        e_log_sticks, e_log_1m_sticks,
                        dp_prior_alpha, allele_prior_alpha,
                        allele_prior_beta) + 1

        ind_admix_update2_ag = cavi_lib.get_stick_update2_ag(g_obs,
                                e_log_pop_freq, e_log_1m_pop_freq,
                                e_log_sticks, e_log_1m_sticks,
                                dp_prior_alpha, allele_prior_alpha,
                                allele_prior_beta) + 1
        
        # should be close
        assert np.abs(ind_admix_update1_ag -  ind_admix_update[:, :, 0]).max() < 1e-8
        assert np.abs(ind_admix_update2_ag -  ind_admix_update[:, :, 1]).max() < 1e-8

        
    def test_population_stick_update(self):
        
        # closed-form update
        pop_beta_update = cavi_lib.update_pop_beta(g_obs, e_log_pop_freq, e_log_1m_pop_freq, 
                                            e_log_cluster_probs, prior_params_dict)[0]
        
        # autodiff updates
        pop_beta_update1_ag = cavi_lib.get_pop_beta_update1_ag(g_obs,
                        e_log_pop_freq, e_log_1m_pop_freq,
                        e_log_sticks, e_log_1m_sticks,
                        dp_prior_alpha, allele_prior_alpha,
                        allele_prior_beta) + 1

        pop_beta_update2_ag = cavi_lib.get_pop_beta_update2_ag(g_obs,
                                e_log_pop_freq, e_log_1m_pop_freq,
                                e_log_sticks, e_log_1m_sticks,
                                dp_prior_alpha, allele_prior_alpha,
                                allele_prior_beta) + 1
        
        # should be close
        assert np.abs(pop_beta_update1_ag -  pop_beta_update[:, :, 0]).max() < 1e-8
        assert np.abs(pop_beta_update2_ag -  pop_beta_update[:, :, 1]).max() < 1e-8

    def test_cavi(self):
        # run cavi in full, with the debugger on

        _ = cavi_lib.run_cavi(g_obs,
                              vb_params_dict,
                              vb_params_paragami,
                              prior_params_dict, 
                              debug = True)

if __name__ == '__main__':
    unittest.main()
