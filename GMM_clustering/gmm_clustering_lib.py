import sys
sys.path.insert(0, './../../LinearResponseVariationalBayes.py')

import LinearResponseVariationalBayes as vb
import LinearResponseVariationalBayes.ExponentialFamilies as ef

import autograd
import autograd.numpy as np
import autograd.scipy as sp

import scipy as osp

import warnings

from scipy import optimize

from sklearn.cluster import KMeans

from copy import deepcopy

from datetime import datetime
import time

import modeling_lib as modeling_lib
import functional_sensitivity_lib as fun_sens_lib

import json
import json_tricks

from numpy.polynomial.hermite import hermgauss

sys.path.append('./../../../paragami/')

import paragami

##########################
# Set up vb parameters
##########################

def get_vb_params_paragami_object(dim, k_approx, n_obs,
                                    use_logitnormal_sticks = True):

    vb_params_paragami = paragami.PatternDict()

    # cluster centroids
    vb_params_paragami['centroids'] = \
        paragami.NumericArrayPattern(shape=(dim, k_approx))

    # BNP sticks
    if use_logitnormal_sticks:
        # variational distribution for each stick is logitnormal
        vb_params_paragami['v_stick_mean'] = \
            paragami.NumericArrayPattern(shape = (k_approx - 1,))
        vb_params_paragami['v_stick_info'] = \
            paragami.NumericArrayPattern(shape = (k_approx - 1,), lb = 1e-4)
    else:
        # else its a beta
        vb_params_paragami['v_sticks_beta'] = \
            paragami.NumericArrayPattern(shape=(2, k_approx - 1), lb = 0.)

    # cluster covariances
    vb_params_paragami['gamma'] = \
        paragami.pattern_containers.PatternArray(shape = (k_approx, ), \
                                    base_pattern = paragami.PSDSymmetricMatrixPattern(size=dim))

    vb_params_dict = vb_params_paragami.random()

    return vb_params_dict, vb_params_paragami

def get_vb_params_from_dict(vb_params_dict):
    # VB parameters
    v_stick_mean = vb_params_dict['v_stick_mean']
    v_stick_info = vb_params_dict['v_stick_info']

    assert len(v_stick_mean) == len(v_stick_info)

    centroids = vb_params_dict['centroids']
    assert np.shape(centroids)[1] == (len(v_stick_info) + 1)

    gamma = vb_params_dict['gamma']

    assert np.shape(centroids)[1] == np.shape(gamma)[0]
    assert np.shape(centroids)[0] == np.shape(gamma)[1]
    assert np.shape(centroids)[0] == np.shape(gamma)[2]

    return v_stick_mean, v_stick_info, centroids, gamma

##########################
# Set up prior parameters
##########################
def get_default_prior_params(dim):
    prior_params_dict = dict()
    prior_params_paragami = paragami.PatternDict()

    # DP prior parameter
    prior_params_dict['alpha'] = np.array([4.0])
    prior_params_paragami['alpha'] = \
        paragami.NumericArrayPattern(shape=(1, ), lb = 0.0)

    # prior on the centroids
    prior_params_dict['prior_centroid_mean'] = np.array([0.0])
    prior_params_paragami['prior_centroid_mean'] = \
        paragami.NumericArrayPattern(shape=(1, ))

    prior_params_dict['prior_centroid_info'] = np.array([0.1])
    prior_params_paragami['prior_centroid_info'] = \
        paragami.NumericArrayPattern(shape=(1, ), lb = 0.0)

    # prior on the variance
    prior_params_dict['prior_gamma_df'] = np.array([8.0])
    prior_params_paragami['prior_gamma_df'] = \
        paragami.NumericArrayPattern(shape=(1, ), lb = 0.0)

    prior_params_dict['prior_gamma_inv_scale'] = 0.62 * np.eye(dim)
    prior_params_paragami['prior_gamma_inv_scale'] = \
        paragami.PSDSymmetricMatrixPattern(size=dim)

    return prior_params_dict, prior_params_paragami

##########################
# Expected prior term
##########################
def get_e_log_prior(v_stick_mean, v_stick_info, centroids, gamma,
                        prior_params_dict,
                        gh_loc, gh_weights,
                        use_logitnormal_sticks = True):

    # prior parameters
    # dp prior
    alpha = prior_params_dict['alpha']

    # wishart prior
    df = prior_params_dict['prior_gamma_df']
    V_inv = prior_params_dict['prior_gamma_inv_scale']

    # centroid priors
    prior_mean = prior_params_dict['prior_centroid_mean']
    prior_info = prior_params_dict['prior_centroid_info']

    if use_logitnormal_sticks:
        dp_prior = \
            modeling_lib.get_e_logitnorm_dp_prior(v_stick_mean, v_stick_info,
                                                alpha, gh_loc, gh_weights)
    else:
        raise NotImplementedError()

    e_gamma_prior = get_e_log_wishart_prior(gamma, df, V_inv)
    e_centroid_prior = get_e_centroid_prior(centroids, prior_mean, prior_info)

    return np.squeeze(e_gamma_prior + e_centroid_prior + dp_prior)

##########################
# Entropy
##########################
def get_entropy(v_stick_mean, v_stick_info, e_z, gh_loc, gh_weights,
                    use_logitnormal_sticks = True):

    z_entropy = modeling_lib.multinom_entropy(e_z)
    if use_logitnormal_sticks:
        stick_entropy = \
            modeling_lib.get_logitnorm_stick_entropy(v_stick_mean, v_stick_info,
                                    gh_loc, gh_weights)
    else:
        raise NotImplementedError()

    return z_entropy + stick_entropy

##########################
# Likelihood term
##########################
def get_loglik_obs_by_nk(y, centroids, gamma):
    # returns a n x k matrix whose nkth entry is
    # the likelihood for the nth observation
    # belonging to the kth cluster

    dim = np.shape(y)[1]

    assert np.shape(y)[1] == np.shape(centroids)[0]
    assert np.shape(gamma)[0] == np.shape(centroids)[1]
    assert np.shape(gamma)[1] == np.shape(centroids)[0]

    data2_term = np.einsum('ni, kij, nj -> nk', y, gamma, y)
    cross_term = np.einsum('ni, kij, jk -> nk', y, gamma, centroids)
    centroid2_term = np.einsum('ik, kij, jk -> k', centroids, gamma, centroids)

    squared_term = data2_term - 2 * cross_term + \
                    np.expand_dims(centroid2_term, axis = 0)

    return - 0.5 * squared_term + 0.5 * np.linalg.slogdet(gamma)[1][None, :]

##########################
# Optimization over e_z
##########################

def get_z_nat_params(y, v_stick_mean, v_stick_info, centroids, gamma,
                        gh_loc, gh_weights,
                        use_bnp_prior = True,
                        return_loglik_obs_by_nk = False):

    # get likelihood term
    loglik_obs_by_nk = get_loglik_obs_by_nk(y, centroids, gamma)

    # get weight term
    if use_bnp_prior:
        e_log_cluster_probs = \
            modeling_lib.get_e_log_cluster_probabilities(
                            v_stick_mean, v_stick_info,
                            gh_loc, gh_weights)
    else:
        e_log_cluster_probs = 0.

    z_nat_param = loglik_obs_by_nk + e_log_cluster_probs

    if return_loglik_obs_by_nk:
        return z_nat_param, loglik_obs_by_nk
    else:
        return z_nat_param

def get_optimal_z(y, v_stick_mean, v_stick_info, centroids, gamma,
                    gh_loc, gh_weights,
                    use_bnp_prior = True,
                    return_loglik_obs_by_nk = False):

    _z_nat_param = \
        get_z_nat_params(y, v_stick_mean, v_stick_info, centroids, gamma,
                                    gh_loc, gh_weights,
                                    use_bnp_prior,
                                    return_loglik_obs_by_nk)

    if return_loglik_obs_by_nk:
        loglik_obs_by_nk = _z_nat_param[1]
        z_nat_param = _z_nat_param[0]

    else:
        z_nat_param = _z_nat_param

    log_const = sp.misc.logsumexp(z_nat_param, axis=1)
    e_z = np.exp(z_nat_param - log_const[:, None])

    if return_loglik_obs_by_nk:
        return e_z, loglik_obs_by_nk
    else:
        return e_z

def get_kl(y, vb_params_dict, prior_params_dict,
                    gh_loc, gh_weights,
                    data_weights = None,
                    use_bnp_prior = True,
                    use_logitnormal_sticks = True):

    # get vb parameters
    v_stick_mean, v_stick_info, centroids, gamma = \
        get_vb_params_from_dict(vb_params_dict)

    # get optimal cluster belongings
    e_z, loglik_obs_by_nk = \
            get_optimal_z(y, v_stick_mean, v_stick_info, centroids, gamma,
                            gh_loc, gh_weights,
                            return_loglik_obs_by_nk = True)

    # weight data if necessary, and get likelihood of y
    if data_weights is not None:
        assert np.shape(data_weights)[0] == n_obs, \
                    'data weights need to be n_obs by 1'
        assert np.shape(data_weights)[1] == 1, \
                    'data weights need to be n_obs by 1'
        e_loglik_obs = np.sum(data_weights * e_z * loglik_obs_by_nk)
    else:
        e_loglik_obs = np.sum(e_z * loglik_obs_by_nk)

    # likelihood of z
    if use_bnp_prior:
        e_loglik_ind = modeling_lib.loglik_ind(v_stick_mean, v_stick_info, e_z,
                            gh_loc, gh_weights,
                            use_logitnormal_sticks)
    else:
        e_loglik_ind = 0.

    e_loglik = e_loglik_ind + e_loglik_obs

    if not np.isfinite(e_loglik):
        print('gamma', vb_params_dict['gamma'].get())
        print('det gamma', np.linalg.slogdet(
            vb_params_dict['gamma'])[1])
        print('cluster weights', np.sum(e_z, axis = 0))

    assert(np.isfinite(e_loglik))

    # entropy term
    entropy = np.squeeze(get_entropy(v_stick_mean, v_stick_info, e_z,
                                        gh_loc, gh_weights,
                                        use_logitnormal_sticks))
    assert(np.isfinite(entropy))

    # prior term
    e_log_prior = get_e_log_prior(v_stick_mean, v_stick_info, centroids, gamma,
                            prior_params_dict,
                            gh_loc, gh_weights,
                            use_logitnormal_sticks)

    assert(np.isfinite(e_log_prior))

    elbo = e_log_prior + entropy + e_loglik

    return -1 * elbo

# just for my convenience
def get_optimal_z_from_vb_params_dict(y, vb_params_dict, gh_loc, gh_weights,
                                        use_bnp_prior = True):

    v_stick_mean, v_stick_info, centroids, gamma = \
        get_vb_params_from_dict(vb_params_dict)

    e_z = get_optimal_z(y, v_stick_mean, v_stick_info, centroids, gamma,
                        gh_loc, gh_weights,
                        use_bnp_prior = True,
                        return_loglik_obs_by_nk = False)

    return e_z

##########################
# Optimization functions
##########################

def cluster_and_get_k_means_inits(y, vb_params_paragami,
                                n_kmeans_init = 1,
                                z_init_eps=0.05):

    # get dictionary of vb parameters
    vb_params_dict = vb_params_paragami.random()

    # data parameters
    k_approx = np.shape(vb_params_dict['centroids'])[1]
    n_obs = np.shape(y)[0]
    dim = np.shape(y)[1]

    # K means init.
    for i in range(n_kmeans_init):
        km = KMeans(n_clusters = k_approx).fit(y)
        enertia = km.inertia_
        if (i == 0):
            enertia_best = enertia
            km_best = deepcopy(km)
        elif (enertia < enertia_best):
            enertia_best = enertia
            km_best = deepcopy(km)

    e_z_init = np.full((n_obs, k_approx), z_init_eps)
    for n in range(len(km_best.labels_)):
        e_z_init[n, km_best.labels_[n]] = 1.0 - z_init_eps
    e_z_init /= np.expand_dims(np.sum(e_z_init, axis = 1), axis = 1)

    vb_params_dict['centroids'] = km_best.cluster_centers_.T

    vb_params_dict['v_stick_mean'] = np.ones(k_approx - 1)
    vb_params_dict['v_stick_info'] = np.ones(k_approx - 1)

    # Set inital covariances
    gamma_init = np.zeros((k_approx, dim, dim))
    for k in range(k_approx):
        indx = np.argwhere(km_best.labels_ == k).flatten()

        if len(indx) == 1:
            # if there's only one datapoint in the cluster,
            # the covariance is not defined.
            gamma_init[k, :, :] = np.eye(dim)
        else:
            resid_k = y[indx, :] - km_best.cluster_centers_[k, :]
            gamma_init_ = np.linalg.inv(np.cov(resid_k.T) + \
                                    np.eye(dim) * 1e-4)
            # symmetrize ... there might be some numerical issues otherwise
            gamma_init[k, :, :] = 0.5 * (gamma_init_ + gamma_init_.T)

    vb_params_dict['gamma'] = gamma_init

    init_free_par = vb_params_paragami.flatten(vb_params_dict, free = True)

    return init_free_par, vb_params_dict, e_z_init



def run_bfgs(get_vb_free_params_loss, init_vb_free_params,
                    get_vb_free_params_loss_grad =  None,
                    maxiter = 10, gtol = 1e-8):
    # `get_vb_free_params_loss` takes in vb free parameters and returns the loss

    if get_vb_free_params_loss_grad is None:
        get_vb_free_params_loss_grad = autograd.grad(get_vb_free_params_loss)

    # optimize
    bfgs_output = optimize.minimize(
            get_vb_free_params_loss,
            x0=init_vb_free_params,
            jac=get_vb_free_params_loss_grad,
            method='BFGS',
            options={'maxiter': maxiter, 'disp': True, 'gtol': gtol})

    bfgs_vb_free_params = bfgs_output.x

    return bfgs_vb_free_params, bfgs_output

def precondition_and_optimize(get_vb_free_params_loss, init_vb_free_params,
                                maxiter = 10, gtol = 1e-8):
    # `get_vb_free_params_loss` takes in vb free parameters and returns the loss

    # get preconditioned function
    precond_fun = paragami.PreconditionedFunction(get_vb_free_params_loss)
    _ = precond_fun.set_preconditioner_with_hessian(x = init_vb_free_params,
                                                        ev_min=1e-4)

    # optimize
    trust_ncg_output = optimize.minimize(
                            method='trust-ncg',
                            x0=precond_fun.precondition(init_vb_free_params),
                            fun=precond_fun,
                            jac=autograd.grad(precond_fun),
                            hess=autograd.hessian(precond_fun),
                            options={'maxiter': maxiter, 'disp': True, 'gtol': gtol})

    # Uncondition
    trust_ncg_vb_free_pars = precond_fun.unprecondition(trust_ncg_output.x)

    return trust_ncg_vb_free_pars, trust_ncg_output

def optimize_full(y, vb_params_paragami, prior_params_dict,
                    init_vb_free_params, gh_loc, gh_weights,
                    bfgs_max_iter = 50, netwon_max_iter = 50,
                    max_precondition_iter = 10,
                    gtol=1e-8, ftol=1e-8, xtol=1e-8):

    # Get loss as a function of the  vb_params_dict
    get_vb_params_loss = paragami.Functor(original_fun=get_kl, argnums=1)
    get_vb_params_loss.cache_args(y, None, prior_params_dict,
                                    gh_loc, gh_weights)

    # Get loss as a function vb_free_params
    get_vb_free_params_loss = paragami.FlattenedFunction(
                                                original_fun=get_vb_params_loss,
                                                patterns=vb_params_paragami,
                                                free=True)
    # get gradient
    get_vb_free_params_loss_grad = autograd.grad(get_vb_free_params_loss)
    get_vb_free_params_loss_hess = autograd.hessian(get_vb_free_params_loss)

    # run a few steps of bfgs
    print('running bfgs ... ')
    bfgs_vb_free_params, bfgs_ouput = run_bfgs(get_vb_free_params_loss,
                                init_vb_free_params,
                                get_vb_free_params_loss_grad,
                                maxiter = bfgs_max_iter, gtol = gtol)
    x = bfgs_vb_free_params
    f_val = get_vb_free_params_loss(x)

    if bfgs_ouput.success:
        print('bfgs converged. Done. ')
        return x

    else:
        # if bfgs did not converge, we precondition and run newton trust region
        for i in range(max_precondition_iter):
            print('\n running preconditioned newton; iter = ', i)
            new_x, ncg_output = precondition_and_optimize(get_vb_free_params_loss, x,\
                                        maxiter = netwon_max_iter, gtol = gtol)

            # Check convergence.
            new_f_val = get_vb_free_params_loss(new_x)
            grad_val = get_vb_free_params_loss_grad(new_x)

            x_diff = np.sum(np.abs(new_x - x))
            f_diff = np.abs(new_f_val - f_val)
            grad_l1 = np.sum(np.abs(grad_val))
            x_conv = x_diff < xtol
            f_conv = f_diff < ftol
            grad_conv = grad_l1 < gtol

            x = new_x
            f_val = new_f_val

            converged = x_conv or f_conv or grad_conv or ncg_output.success

            print('Iter {}: x_diff = {}, f_diff = {}, grad_l1 = {}'.format(
                i, x_diff, f_diff, grad_l1))

            if converged:
                print('done. ')
                break

        return new_x


########################
# Sensitivity functions
#######################

def get_moments_from_vb_free_params(vb_params_paragami, vb_params_free):
    vb_params_dict = vb_params_paragami.fold(vb_params_free, free = True)

    return vb_params_paragami.flatten(vb_params_dict, free = False), \
                vb_params_dict

def get_e_num_pred_clusters_from_vb_free_params(vb_params_paragami,
                                                    vb_params_free,
                                                    n_obs,
                                                    threshold = 0,
                                                    n_samples = 100000):
    # get posterior predicted number of clusters

    _, vb_params_dict = \
        get_moments_from_vb_free_params(vb_params_paragami, vb_params_free)

    mu = vb_params_dict['v_stick_mean']
    sigma = 1 / np.sqrt(vb_params_dict['v_stick_info'])

    return modeling_lib.get_e_number_clusters_from_logit_sticks(mu, sigma,
                                                        n_obs,
                                                        threshold = threshold,
                                                        n_samples = n_samples)


# Get the expected posterior number of distinct clusters.
def get_e_num_clusters_from_free_par(y, vb_params_paragami, vb_params_free,
                                        gh_loc, gh_weights,
                                        threshold = 0,
                                        n_samples = 100000):

    _, vb_params_dict = \
        get_moments_from_vb_free_params(vb_params_paragami, vb_params_free)

    e_z  = get_optimal_z_from_vb_params_dict(y, vb_params_dict, gh_loc, gh_weights,
                                            use_bnp_prior = True)

    return modeling_lib.get_e_num_large_clusters_from_ez(e_z,
                                        threshold = threshold,
                                        n_samples = 100000)

# class ExpectedPredNumClusters(object):
#     # Get the expected posterior predictive number of distinct clusters above
#     # some given threshold.
#     # Note that we cache the normal samples that we use to sample
#     # cluster belongings.
#
#     def __init__(self, model):
#         self.model = model
#         self.n_obs = self.model.y.shape[0]
#         self.k_approx = self.model.k_approx
#
#         self.set_normal_samples()
#
#     def set_normal_samples(self, n_samples = 10000):
#         self.unv_norm_samples = np.random.normal(0, 1, \
#                                     size = (n_samples, self.k_approx - 1))
#
#     def get_e_num_pred_heavy_clusters_from_free_par(self, free_par, threshold = 0):
#         self.model.global_vb_params.set_free(free_par)
#         self.model.set_optimal_z()
#
#         mu = self.model.global_vb_params['v_sticks']['mean'].get()
#         sigma = 1 / np.sqrt(self.model.global_vb_params['v_sticks']['info'].get())
#
#         return modeling_lib.get_e_number_clusters_from_logit_sticks(
#                                     mu, sigma, self.n_obs,
#                                     threshold = threshold,
#                                     unv_norm_samples = self.unv_norm_samples)
#
# class ExpectedNumClustersFromZ(object):
#     # Get the expected posterior number of distinct clusters above
#     # some given threshold.
#     # Note that we cache the uniform samples that we use to sample
#     # cluster belongings.
#
#     def __init__(self, model):
#         self.model = model
#         self.n_obs = self.model.y.shape[0]
#
#         self.set_uniform_samples()
#
#     def set_uniform_samples(self, n_samples = 10000):
#         self.unif_samples = np.random.random((self.n_obs, n_samples))
#
#     def get_e_num_heavy_clusters_from_free_par(self, free_par, threshold = 0):
#         self.model.global_vb_params.set_free(free_par)
#         self.model.set_optimal_z()
#
#         return modeling_lib.get_e_num_large_clusters_from_ez(self.model.e_z,
#                                                 threshold = threshold,
#                                                 unif_samples = self.unif_samples)
