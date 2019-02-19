import autograd
import autograd.numpy as np
import autograd.scipy as sp

from scipy import optimize

from sklearn.cluster import KMeans

from copy import deepcopy

import paragami
from paragami import OptimizationObjective

from sklearn.decomposition import NMF

import time

import dp_modeling_lib

def cluster_and_get_init(g_obs, k):
    # g_obs should be n_obs x n_loci x 3,
    # a one-hot encoding of genotypes
    assert len(g_obs.shape) == 3

    # convert one-hot encoding to probability of A genotype, {0, 0.5, 1}
    x = g_obs.argmax(axis = 2) / 2

    # run NMF
    model = NMF(n_components=k, init='random')
    init_ind_admix_propn_unscaled = model.fit_transform(x)
    init_pop_allele_freq_unscaled = model.components_.T

    # divide by largest allele frequency, so all numbers between 0 and 1
    denom_pop_allele_freq = np.max(init_pop_allele_freq_unscaled)
    init_pop_allele_freq = init_pop_allele_freq_unscaled / \
                                denom_pop_allele_freq

    # normalize rows
    denom_ind_admix_propn = \
        init_ind_admix_propn_unscaled.sum(axis = 1, keepdims = True)
    init_ind_admix_propn = \
        init_ind_admix_propn_unscaled / denom_ind_admix_propn
    # clip again and renormalize
    init_ind_admix_propn = init_ind_admix_propn.clip(0.05, 0.95)
    init_ind_admix_propn = init_ind_admix_propn / \
                            init_ind_admix_propn.sum(axis = 1, keepdims = True)

    return init_ind_admix_propn, init_pop_allele_freq.clip(0.05, 0.95)

def set_init_vb_params(g_obs, k_approx, vb_params_dict):
    # get initial admixtures, and population frequencies
    init_ind_admix_propn, init_pop_allele_freq = \
            cluster_and_get_init(g_obs, k_approx)

    # set bnp parameters for individual admixture
    # set mean to be logit(stick_breaking_propn), info to be 1
    stick_break_propn = \
        dp_modeling_lib.get_stick_break_propns_from_mixture_weights(init_ind_admix_propn)
    ind_mix_stick_propn_mean = np.log(stick_break_propn) - np.log(1 - stick_break_propn)
    ind_mix_stick_propn_info = np.ones(stick_break_propn.shape)

    # set beta paramters for population paramters
    # set beta = 1, alpha to have the correct mean
    pop_freq_beta_params1 = init_pop_allele_freq / (1 - init_pop_allele_freq)
    pop_freq_beta_params2 = np.ones(init_pop_allele_freq.shape)
    pop_freq_beta_params = np.concatenate((pop_freq_beta_params1[:, :, None],
                                       pop_freq_beta_params2[:, :, None]), axis = 2)

    vb_params_dict['ind_mix_stick_propn_mean'] = ind_mix_stick_propn_mean
    vb_params_dict['ind_mix_stick_propn_info'] = ind_mix_stick_propn_info
    vb_params_dict['pop_freq_beta_params'] = pop_freq_beta_params

    return vb_params_dict

def run_bfgs(get_loss, init_vb_free_params,
                    maxiter = 10, gtol = 1e-8):

    """
    Runs BFGS to find the optimal variational parameters

    Parameters
    ----------
    get_loss : Callable function
        A callable function that takes in the variational free parameters
        and returns the negative ELBO.
    init_vb_free_params : vector
        Vector of the free variational parameters at which we initialize the
        optimization.
    get_loss_grad : Callable function (optional)
        A callable function that takes in the variational free parameters
        and returns the gradient of get_loss.
    maxiter : int
        Maximum number of iterations to run bfgs.
    gtol : float
        The tolerance used to check that the gradient is approximately
            zero at the optimum.

    Returns
    -------
    bfgs_vb_free_params : vec
        Vector of optimal variational free parameters.
    bfgs_output :
        The OptimizeResult class from returned by scipy.optimize.minimize.

    """
    get_loss_objective = OptimizationObjective(get_loss)

    # optimize
    bfgs_output = optimize.minimize(
            get_loss_objective.f,
            x0=init_vb_free_params,
            jac=get_loss_objective.grad,
            method='BFGS',
            options={'maxiter': maxiter, 'disp': True, 'gtol': gtol})

    bfgs_vb_free_params = bfgs_output.x

    return bfgs_vb_free_params, bfgs_output

def precondition_and_optimize(get_loss, init_vb_free_params,
                                maxiter = 10, gtol = 1e-8):
    """
    Finds a preconditioner at init_vb_free_params, and then
    runs trust Newton conjugate gradient to find the optimal
    variational parameters.

    Parameters
    ----------
    get_loss : Callable function
        A callable function that takes in the variational free parameters
        and returns the negative ELBO.
    init_vb_free_params : vector
        Vector of the free variational parameters at which we initialize the
        optimization.
    get_loss_grad : Callable function (optional)
        A callable function that takes in the variational free parameters
        and returns the gradient of get_loss.
    maxiter : int
        Maximum number of iterations to run Newton
    gtol : float
        The tolerance used to check that the gradient is approximately
            zero at the optimum.

    Returns
    -------
    bfgs_vb_free_params : vec
        Vector of optimal variational free parameters.
    bfgs_output : class OptimizeResult from scipy.Optimize

    """

    # get preconditioned function
    print('computing preconditioner ')
    t0 = time.time()
    precond_fun = paragami.PreconditionedFunction(get_loss)
    _ = precond_fun.set_preconditioner_with_hessian(x = init_vb_free_params,
                                                        ev_min=1e-4)
    print('preconditioning time: {0:.2f}'.format(time.time() - t0))

    # optimize
    get_loss_precond_objective = OptimizationObjective(precond_fun)
    print('running newton steps')
    trust_ncg_output = optimize.minimize(
                            method='trust-ncg',
                            x0=precond_fun.precondition(init_vb_free_params),
                            fun=get_loss_precond_objective.f,
                            jac=get_loss_precond_objective.grad,
                            hessp=get_loss_precond_objective.hessian_vector_product,
                            options={'maxiter': maxiter, 'disp': True, 'gtol': gtol})

    # Uncondition
    trust_ncg_vb_free_pars = precond_fun.unprecondition(trust_ncg_output.x)

    return trust_ncg_vb_free_pars, trust_ncg_output

def optimize_full(get_loss, init_vb_free_params,
                    bfgs_max_iter = 50, netwon_max_iter = 50,
                    max_precondition_iter = 10,
                    gtol=1e-8, ftol=1e-8, xtol=1e-8):
    """
    Finds the optimal variational free parameters of using a combination of
    BFGS and Newton trust region conjugate gradient.

    Runs a few BFGS steps, and computes a preconditioner at the BFGS optimum.
    After preconditioning, we run Newton trust region conjugate gradient.
    If the tolerance is not satisfied after Newton steps, we compute another
    preconditioner and repeat.

    Parameters
    ----------
    get_loss : Callable function
        A callable function that takes in the variational free parameters
        and returns the negative ELBO.
    init_vb_free_params : vector
        Vector of the free variational parameters at which we initialize the
    bfgs_max_iter : int
        Maximum number of iterations to run initial BFGS.
    newton_max_iter : int
        Maximum number of iterations to run Newton steps.
    max_precondition_iter : int
        Maximum number of times to recompute preconditioner.
    ftol : float
        The tolerance used to check that the difference in function value
        is approximately zero at the last step.
    xtol : float
        The tolerance used to check that the difference in x values in the L
        infinity norm is approximately zero at the last step.
    gtol : float
        The tolerance used to check that the gradient is approximately
            zero at the optimum.

    Returns
    -------
    vec
        A vector of optimal variational free parameters.

    """

    get_loss_grad = autograd.grad(get_loss)

    # run a few steps of bfgs
    print('running bfgs ... ')
    bfgs_vb_free_params, bfgs_ouput = run_bfgs(get_loss,
                                init_vb_free_params,
                                maxiter = bfgs_max_iter,
                                gtol = gtol)
    x = bfgs_vb_free_params
    f_val = get_loss(x)

    if bfgs_ouput.success:
        print('bfgs converged. Done. ')
        return x

    else:
        # if bfgs did not converge, we precondition and run newton trust region
        for i in range(max_precondition_iter):
            print('\n running preconditioned newton; iter = ', i)
            new_x, ncg_output = precondition_and_optimize(get_loss, x,\
                                        maxiter = netwon_max_iter, gtol = gtol)

            # Check convergence.
            new_f_val = get_loss(new_x)
            grad_val = get_loss_grad(new_x)

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
