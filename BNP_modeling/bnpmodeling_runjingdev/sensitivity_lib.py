# this is a bare-bones version of vittles.HyperparameterSensitivityLinearApproximation
# implemented in jax

import jax
import jax.numpy as np

import time

from vittles.solver_lib import get_cholesky_solver

class HyperparameterSensitivityLinearApproximation(object):
    def __init__(self,
                    objective_fun,
                    opt_par_value,
                    hyper_par_value0,
                    hyper_par_objective_fun = None):

        self.objective_fun = objective_fun
        self.opt_par_value = opt_par_value
        self.hyper_par_value0 = hyper_par_value0
        if hyper_par_objective_fun is None:
            self.hyper_par_objective_fun = objective_fun
        else:
            self.hyper_par_objective_fun = hyper_par_objective_fun

        # define derivatives
        self.dobj_dhyper = jax.jit(jax.jacobian(self.hyper_par_objective_fun, 1))
        self.dobj_dhyper_dinput = jax.jit(jax.jacobian(self.hyper_par_objective_fun), 0)

        self.hess_fun = jax.jit(jax.hessian(self.objective_fun, argnums = 0))

        # compile derivatives
        print('Compiling objective function derivatives ... ')
        t0 = time.time()
        _ = self._compute_objective_derivatives()
        print('Compile time: {0:.3g}sec'.format(time.time() - t0))

        # compute derivatives
        t0 = time.time()
        self.cross_hess, self.hessian = self._compute_objective_derivatives()
        print('\nObjective function derivative time: {0:.3g}sec'.format(time.time() - t0))

        # get dinput_dhyper
        t0 = time.time()
        self.dinput_dhyper = self._solve_system()
        print('Linear system time: {0:.3g}sec'.format(time.time() - t0))

        # get dinput_dhyper
        t0 = time.time()
        self.dinput_dhyper = self._solve_system()
        print('Linear system time: {0:.3g}sec'.format(time.time() - t0))

    def _compute_objective_derivatives(self):
        cross_hess = self.dobj_dhyper_dinput(self.opt_par_value, self.hyper_par_value0)
        hessian = self.hess_fun(self.opt_par_value, self.hyper_par_value0)

        return cross_hess, hessian

    def _solve_system(self):
        chol_solver = get_cholesky_solver(self.hessian)
        return -chol_solver(self.cross_hess)

    def predict_opt_par_from_hyper_par(self, hyper_par_value):
        delta = (hyper_par_value - self.hyper_par_value0)
        return np.dot(self.dinput_dhyper, delta) + self.opt_par_value
