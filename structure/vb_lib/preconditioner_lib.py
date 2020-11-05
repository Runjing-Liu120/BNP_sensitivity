import jax
import jax.numpy as np
import jax.scipy as sp

import paragami

from paragami.optimization_lib import _get_sym_matrix_inv_sqrt_funcs, \
                                        _get_matrix_from_operator

def get_log_beta_covariance(alpha, beta, return_sqrt):
    # returns the covariance of the score function
    # of the beta distribution

    digamma_sum = sp.special.polygamma(1, alpha + beta)

    # get Fisher's information matrix
    I11 = sp.special.polygamma(1, alpha) - digamma_sum # var(log x)
    I22 = sp.special.polygamma(1, beta) - digamma_sum # var(log(1 - x))
    I12 = - digamma_sum # cov(log x, log(1 - x))

    # mulitply by alphas and betas because we are using
    # an unconstrained parameterization, where log(alpha) = free_param
    # TODO: better way to do this using autodiff?
    
    out = np.array([[I11 * alpha**2, I12 * alpha * beta], \
                     [I12 * alpha * beta, I22 * beta**2]])
    
    if return_sqrt: 
        sqrt_fun = _get_sym_matrix_inv_sqrt_funcs(out)[0]
        return np.array([sqrt_fun(np.array([1., 0.])), \
                         sqrt_fun(np.array([0., 1.]))])
    else: 
        return out

def _eval_popbeta_cov_matmul(vb_params_pop_params, return_info, return_sqrt, v):
    xs = vb_params_pop_params.reshape(-1, 2)
    xs = np.concatenate((xs, v.reshape(-1, 2)), axis = 1)

    def f(carry, x):

        cov = get_log_beta_covariance(x[0], x[1], return_sqrt)

        if return_info:
            cov = np.linalg.inv(cov)


        return carry, np.dot(cov, x[2:4])

    out = jax.lax.scan(f, init = 0., xs = xs)

    return out[1].flatten()

def get_mfvb_cov_matmul(v, vb_params_dict,
                        vb_params_paragami,
                        return_info = False, 
                        return_sqrt = False):

    # compute preconditioner from MFVB covariances

    block_mfvb_cov = ()

    ##############
    # blocks for the population frequency
    vb_params_pop_params = vb_params_paragami['pop_freq_beta_params'].flatten(\
                        vb_params_dict['pop_freq_beta_params'], free = False)

    block1_dim = len(vb_params_pop_params)
    block1 = _eval_popbeta_cov_matmul(vb_params_pop_params, 
                                      return_info, return_sqrt,
                                      v[0:block1_dim])

    #############
    # blocks for individual admixture
    v2 = v[block1_dim:]
    use_logitnormal_sticks = 'stick_means' in vb_params_dict['ind_admix_params'].keys()
    if use_logitnormal_sticks:
        infos = vb_params_paragami['ind_admix_params']['stick_infos'].flatten(
                        vb_params_dict['ind_admix_params']['stick_infos'],
                        free = False)
        a1 = infos 
        a2 = 0.5
        
        if return_sqrt: 
            a1 = np.sqrt(infos)
            a2 = np.sqrt(a2)
        
        if return_info:
            block2 = np.concatenate((1/a1 * v2[0:len(infos)], v2[len(infos):] * 1/a2))
        else:
            block2 = np.concatenate((a1 * v2[0:len(infos)], v2[len(infos):] * a2))
    else:
        vb_params_admix = vb_params_paragami['ind_admix_params']['stick_beta'].flatten(\
                            vb_params_dict['ind_admix_params']['stick_beta'], free = False)

        block2 = _eval_popbeta_cov_matmul(vb_params_admix, return_info,
                                          return_sqrt, v2)

    return np.concatenate((block1, block2))
