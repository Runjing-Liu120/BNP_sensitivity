import autograd
import autograd.numpy as np

from bnpmodeling_runjingdev.modeling_lib import my_slogdet3d

from scipy import sparse
from itertools import product

import paragami

def get_nat_vec(mvn_free_params, mvn_params_paragami, mvn_nat_params_paragami):

    nat_params_dict = {}

    mvn_param_dict = mvn_params_paragami.fold(mvn_free_params, free = True)

    mean = mvn_param_dict['mean']
    info = mvn_param_dict['info']

    nat_params_dict['nat1'] = np.einsum('ij, j -> i', info, mean)
    nat_params_dict['neg_nat2'] = 0.5 * info

    return mvn_nat_params_paragami.flatten(nat_params_dict, free = False)

def get_mvn_log_partition(nat_vec, mvn_nat_params_paragami):

    nat_params_dict = mvn_nat_params_paragami.fold(nat_vec, free = False)

    nat1 = nat_params_dict['nat1']
    neg_nat2 = nat_params_dict['neg_nat2']

    nat2_inv = np.linalg.inv(-neg_nat2)

    nat2_inv_nat1 = np.einsum('ij, j -> i', nat2_inv, nat1)
    squared_term = np.dot(nat1, nat2_inv_nat1)

    return - 0.25 * squared_term - 0.5 * np.linalg.slogdet(2 * neg_nat2)[1]

get_jac_term = autograd.jacobian(get_nat_vec, 0)
get_log_part_hess = autograd.hessian(get_mvn_log_partition, 0)

def get_mvn_paragami_objects(dim):
    mvn_nat_params_paragami = paragami.PatternDict()
    mvn_nat_params_paragami['nat1'] = \
        paragami.NumericArrayPattern(shape=(dim, ))
    mvn_nat_params_paragami['neg_nat2'] = \
        paragami.PSDSymmetricMatrixPattern(size=dim)

    mvn_params_paragami = paragami.PatternDict()
    mvn_params_paragami['mean'] = \
        paragami.NumericArrayPattern(shape=(dim, ))
    mvn_params_paragami['info'] = \
        paragami.PSDSymmetricMatrixPattern(size=dim)

    return mvn_params_paragami, mvn_nat_params_paragami


def get_fishers_info(mvn_free_params, dim):
    # returns fisher's information
    # for the canonical parameters, in their free parameterization

    # get paragami objects
    mvn_params_paragami, mvn_nat_params_paragami = \
        get_mvn_paragami_objects(dim)

    # vector of natural parameters
    nat_vec = get_nat_vec(mvn_free_params, mvn_params_paragami, mvn_nat_params_paragami)

    fishers_info = get_log_part_hess(nat_vec, mvn_nat_params_paragami)

    jac_term = get_jac_term(mvn_free_params, mvn_params_paragami, mvn_nat_params_paragami)

    return np.dot(jac_term.transpose(), np.dot(fishers_info, jac_term))

def get_gmm_preconditioner(vb_free_params, vb_params_paragami):
    preconditioner = sparse.lil_matrix((len(vb_free_params), len(vb_free_params)))

    bool_dict = vb_params_paragami.empty_bool(False)

    k_approx = bool_dict['cluster_params']['centroids'].shape[1]
    dim = bool_dict['cluster_params']['centroids'].shape[0]

    # get preconditioners for cluster parameters
    for k in range(k_approx):
        bool_dict['cluster_params']['centroids'][:, k] = True
        bool_dict['cluster_params']['cluster_info'][k] = True

        # get indices
        indx_cluster_params_k = vb_params_paragami.flat_indices(bool_dict, free = True)
        indx_product = np.array(list(product(indx_cluster_params_k, indx_cluster_params_k)))

        # get free parameters
        free_params_cluster_params_k = vb_free_params[indx_cluster_params_k]

        # fisher information
        fishers_info_cluster_params_k = get_fishers_info(free_params_cluster_params_k, dim)

        # update preconditioner
        preconditioner[indx_product[:, 0], indx_product[:, 1]] = \
            np.linalg.inv(fishers_info_cluster_params_k).flatten()


        # reset dictionary
        bool_dict = vb_params_paragami.empty_bool(False)

    # get preconditioners for stick parameters
    # unfortunately we cannot use the functions above for the multivariate normal :(
    # I didn't constrain the stick info using the PSD matrix class

    # OK, first step, lets isolate the stick parameters we need:
    bool_dict = vb_params_paragami.empty_bool(False)
    bool_dict['stick_params']['stick_propn_mean'] += True
    bool_dict['stick_params']['stick_propn_info'] += True

    stick_free_params = vb_free_params[vb_params_paragami.flat_indices(bool_dict, free = True)]
    stick_params_dict = vb_params_paragami['stick_params'].fold(stick_free_params, free = True)

    # the jacobian for the sticks
    stick_freeing_jac = \
        vb_params_paragami['stick_params'].freeing_jacobian(stick_params_dict,
                                                            sparse = False)

    # reset boolean dictionaries
    bool_dict = vb_params_paragami.empty_bool(False)
    stick_bool_dict = vb_params_paragami['stick_params'].empty_bool(False)

    for k in range(k_approx - 1):
        bool_dict['stick_params']['stick_propn_mean'][k] = True
        bool_dict['stick_params']['stick_propn_info'][k] = True

        # indices in full vb parameters
        indx_stick_params_k = vb_params_paragami.flat_indices(bool_dict, free = True)
        indx_product = np.array(list(product(indx_stick_params_k, indx_stick_params_k)))

        # indices within stick parameters
        stick_bool_dict['stick_propn_mean'][k] = True
        stick_bool_dict['stick_propn_info'][k] = True
        indx2_stick_params_k = vb_params_paragami['stick_params'].flat_indices(stick_bool_dict, free = True)

        # get jacobian
        stick_jac = np.diag(1 / np.diag(stick_freeing_jac)[indx2_stick_params_k])

        # fisher information
        fishers_info = get_uvn_fisher_info(stick_params_dict['stick_propn_mean'][k],
                                    stick_params_dict['stick_propn_info'][k])

        # update preconditioner
        preconditioner[indx_product[:, 0], indx_product[:, 1]] = \
            np.linalg.inv(np.dot(stick_jac, np.dot(fishers_info, stick_jac))).flatten()

        # reset dictionary
        bool_dict = vb_params_paragami.empty_bool(False)
        stick_bool_dict = vb_params_paragami['stick_params'].empty_bool(False)

    return preconditioner


def get_uvn_fisher_info(mean, info):
    return np.array([[info, 0], [0, 0.5 / info**2]])

#######################
# Function for nystrom woodbury preconditioner
#######################
def get_nystrom_woodbury_approx(A, indx):
    C = A[:, indx]
    CTC = np.dot(C.transpose(), C)

    A_block = A[indx][:, indx]

    inv_term = np.linalg.inv(np.eye(C.shape[1]) - np.linalg.solve(A_block, CTC))

    w_inv_ct = np.linalg.solve(A_block, C.transpose())
    w_inv_ct_dot_x = lambda x : np.dot(w_inv_ct, x)

    term2 = np.dot(C, inv_term)

    woodb_inv_fun = lambda x : x + np.dot(term2, w_inv_ct_dot_x(x))

    return woodb_inv_fun, C, A_block

def get_nystrom_woodbury_precon(hess, indx, lambda_max):
    # doesn't have to actually be the hessian : could be appropriate sub-block
    A = np.eye(hess.shape[0]) - hess / lambda_max
    woodb_inv, _, _ = get_nystrom_woodbury_approx(A, indx)
    nystrom_precond = lambda x : woodb_inv(x) / lambda_max

    return sparse.linalg.LinearOperator(hess.shape,
                                            matvec = nystrom_precond)