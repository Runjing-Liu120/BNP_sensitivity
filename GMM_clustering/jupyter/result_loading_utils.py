import os
import re

import matplotlib.pyplot as plt

import jax.numpy as np

import numpy as onp

import paragami

from bnpmodeling_runjingdev import log_phi_lib
import bnpmodeling_runjingdev.functional_sensitivity_lib as func_sens_lib

lr_color = '#d95f02'
refit_color = '#1b9e77'

class GMMResultsLoader(object):

    def __init__(self,
                 alpha0 = 4.0,
                 out_folder = '../fits/',
                 out_filename = 'iris_fit', 
                 stick_key = 'stick_params'): 
        
        # file paths
        self.out_filename = out_filename 
        self.out_folder = out_folder
        
        # inital alpha 
        self.alpha0 = alpha0
        
        # name of the stick parameters in 
        # the vb params dictionary 
        self.stick_key = stick_key
                
        self._set_init_fit()
        self._set_lr_data()
        
    def _set_init_fit(self): 
        
        # initial fit file
        init_fit_file = self.out_folder + self.out_filename + \
                                '_alpha' + str(self.alpha0) + '.npz'

        print('loading initial fit from: ', init_fit_file)

        vb_init_dict, self.vb_params_paragami, self.init_fit_meta_data = \
            paragami.load_folded(init_fit_file)
        
        self.vb_init_free = self.vb_params_paragami.flatten(vb_init_dict,
                                                       free = True)    
    
    def _set_lr_data(self): 
        
        lr_file = self.out_folder + self.out_filename + \
                    '_alpha' + str(self.alpha0) + '_lrderivatives.npz'
        
        print('loading lr derivatives from: ', lr_file)
        
        lr_data = np.load(lr_file)
        assert lr_data['alpha0'] == self.alpha0
        assert np.abs(lr_data['vb_opt'] - self.vb_init_free).max() < 1e-12
        assert np.abs(lr_data['kl'] - self.init_fit_meta_data['final_kl']) < 1e-8
        self.lr_data = lr_data
        
    def _load_refit_files(self, perturbation, delta): 

        # get all files for that particular perturbation
        match_crit = self.out_filename + '_' + perturbation + \
                        '_delta{}_eps'.format(delta) + '\d+.npz'
        
        refit_files = [f for f in os.listdir(self.out_folder) if re.match(match_crit, f)]

        assert len(refit_files) > 0, 'no refit files found'

        # load files
        optim_time_vec = [self.init_fit_meta_data['optim_time']]
        epsilon_vec = [0.]
        vb_refit_list = [self.vb_init_free]

        for i in range(len(refit_files)): 

            # print('loading fit from: ', refit_files[i])
            vb_params_dict, vb_params_paragami, meta_data = \
                paragami.load_folded(self.out_folder + refit_files[i])

            optim_time_vec.append(meta_data['optim_time'])
            epsilon_vec.append(meta_data['epsilon'])
            vb_refit_list.append(vb_params_paragami.flatten(vb_params_dict, free = True))
            assert meta_data['delta'] == delta
            assert meta_data['alpha'] == self.alpha0
        
        optim_time_vec = np.array(optim_time_vec)
        epsilon_vec = np.array(epsilon_vec)
        vb_refit_list = np.array(vb_refit_list)

        # sort the epsilons 
        _indx = np.argsort(epsilon_vec)
        optim_time_vec = optim_time_vec[_indx]
        epsilon_vec = epsilon_vec[_indx]
        vb_refit_list = vb_refit_list[_indx]

        print('Optim time at epsilon = 1: {:.3f}secs'.format(optim_time_vec[-1]))

        return vb_refit_list, epsilon_vec
    
    def _get_lr_free_params(self, perturbation, epsilon_vec, delta): 
        # Function to load linear response derivatives and their predicted free parameters
        
        der_time = self.lr_data['lr_time_' + perturbation]
        dinput_hyper = self.lr_data['dinput_dfun_' + perturbation]
        
        print('Derivative time: {:.3f}secs'.format(der_time))
        
        def predict_opt_par_from_hyper_par(epsilon): 
            return self.vb_init_free + dinput_hyper * epsilon * delta

        lr_list = []
        for epsilon in epsilon_vec: 
            # get linear response
            lr_list.append(predict_opt_par_from_hyper_par(epsilon))

        return np.array(lr_list)
    
    def get_free_param_result_arrays(self, perturbation, delta):
        # wrapper function to load everything

        vb_refit_list, epsilon_vec = \
            self._load_refit_files(perturbation, delta)

        lr_list = self._get_lr_free_params(perturbation,
                                          epsilon_vec,
                                          delta)

        return vb_refit_list, lr_list, epsilon_vec
    
    def plot_perturbation(self, perturbation, delta): 
            
        # get functional perturbation objectives
        # a lot of arguments are "none" because we just 
        # need the bare minimum to make plots
        f_obj_all = log_phi_lib.LogPhiPerturbations(vb_params_paragami = None, 
                                                     alpha0 = self.alpha0,
                                                     gh_loc = None, 
                                                     gh_weights = None,
                                                     logit_v_grid = None, 
                                                     influence_grid = None, 
                                                     delta = delta,
                                                     stick_key = self.stick_key)

        f_obj = getattr(f_obj_all, 'f_obj_' + perturbation)

        # compute the prior perturbations
        prior_perturbation = func_sens_lib.PriorPerturbation(
                                        alpha0 = self.alpha0,
                                        log_phi = f_obj.log_phi, 
                                        logit_v_ub = 10, 
                                        logit_v_lb = -10)

        prior_perturbation.plot_perturbation();

        return prior_perturbation
    
########################
# Some metrics
########################
def get_metrics(refit, lr, init): 
    
    diff_refit = refit - init
    diff_lr = lr - init
    
    # mean and median errors
    mean_ae = np.abs(refit - lr).mean()
    med_ae = np.median(np.abs(refit - lr))
    
    # r2 
    r_value = osp.stats.linregress(diff_refit,
                                   diff_lr).rvalue
    
    # proportion with correct signs
    sign_correct = np.mean(np.sign(diff_refit) == np.sign(diff_lr))
    return mean_ae, med_ae, r_value, sign_correct

def print_metrics(refit, lr, init, ax): 
    
    mean_ae, med_ae, r_value, sign_correct = \
        get_metrics(refit, lr, init)
    
    # print metrics in an matplotlib plot
    # this is hacky ... can we just print a table?
    # Hide axes
    ax.xaxis.set_visible(False) 
    ax.yaxis.set_visible(False)
    
    # mae 
    ax.text(0.05, 0.9, 
               'mean absolute error: {:.03f}'.format(mean_ae),
               fontsize=15)
    ax.text(0.05, 0.8, 
               'median absolute error: {:.03f}'.format(med_ae),
               fontsize=15)
    
    # R2 
    ax.text(0.05, 0.7, 
               'R2: {:.03f}'.format(r_value),
               fontsize=15)

    # proportion that had the correct sign 
    ax.text(0.05, 0.6, 
               'propn sign correct:  {:.03f}'.format(sign_correct),
               fontsize=15)
    
########################
# lr vs refit scatter plot
########################
def print_diff_plot(refit, lr, init, ax, title = '', alpha = 0.05): 
    
    diff_refit = refit - init
    diff_lr = lr - init
    
    # scatter plot
    ax.scatter(diff_refit, 
               diff_lr, 
               marker = 'o', 
               color = 'red', 
               alpha = alpha)   
    ax.set_xlabel('refit - init')
    ax.set_ylabel('lr - init')
    
    # x = y line
    ax.plot(diff_refit, diff_refit, '-', color = 'blue')
    ax.set_title(title)
    
    # Draw contours
#     nbins = 20
#     x, y = diff_refit, diff_lr
#     gauss_kde = kde.gaussian_kde(np.array([x, y]))
#     xi, yi = onp.mgrid[x.min():x.max():nbins*1j, y.min():y.max():nbins*1j]
#     zi = gauss_kde(np.vstack([xi.flatten(), yi.flatten()]))
#     zi = (zi - zi.min()) / (zi.max() - zi.min())
#     ax[0].contour(xi, yi, zi.reshape(xi.shape), 
#                   levels = [0.001, 0.01, 0.1], 
#                 colors = 'grey')



########################
# useful for plotting coclustering matrices
########################
def plot_colormaps(refit_matr, lr_matr, init_matr, fig, ax, 
                   plot_initial = True): 
    
    i = 0
    if plot_initial:
        # plot initial 
        ax[i].set_title('initial')
        im0 = ax[i].matshow(init_matr, 
                            cmap = plt.get_cmap('Blues'))
        fig.colorbar(im0, ax = ax[i])
        i+=1

    # plot refit - initial 
    diff_refit = refit_matr - init_matr
    vmax = np.abs(diff_refit).max()
    ax[i].set_title('refit - init')
    im1 = ax[i].matshow(diff_refit, 
                        vmax = vmax,
                        vmin = -vmax, 
                        cmap = plt.get_cmap('bwr'))
    fig.colorbar(im1, ax = ax[i])
    i+=1 
    
    # plot lr - initial
    ax[i].set_title('lr - init')
    diff_lr = lr_matr - init_matr
    vmax = np.abs(diff_lr).max()
    im2 = ax[i].matshow(diff_lr,
                        vmax = vmax,
                        vmin = -vmax,
                        cmap = plt.get_cmap('bwr'))
    fig.colorbar(im2, ax = ax[i])

######################
# function to make trace plots
######################
def plot_post_stat_per_epsilon(g, refit_vb_list, lr_list, epsilon_vec, ax): 
    
    # plots the posterior quantity as a function of epsilon
    
    post_vec_refit = onp.zeros(len(epsilon_vec))
    post_vec_lr = onp.zeros(len(epsilon_vec))
    
    for i in range(len(epsilon_vec)): 
        post_vec_refit[i] = g(refit_vb_list[i])
        post_vec_lr[i] = g(lr_list[i])

    # plot refit
    ax.plot(epsilon_vec,
            post_vec_refit, 
            'o-', 
            color = refit_color,
            label = 'refit')
    
    # plot refit
    ax.plot(epsilon_vec,
            post_vec_lr, 
            'o-', 
            color = lr_color,
            label = 'lr')
    ax.set_xlabel('epsilon')
    
    
###################
# function to plot mixture weights
###################

def _plot_weights(weights, ax, jitter = 0., color = 'blue', label = ''): 
    x = np.arange(len(weights)) + jitter
    ax.scatter(x, weights, color = color, label = label)
    ax.bar(x, weights, width = 0.1, color = color)

def plot_mixture_weights(weights_refit, weights_lr, weights_init, ax): 
    
    # initial 
    _plot_weights(weights_init, 
                  ax,
                  jitter = -0.3,
                  color = 'lightblue', 
                  label = 'init')
    
    # linear response
    _plot_weights(weights_lr, 
                  ax,
                  jitter = 0.3,
                  color = lr_color,
                  label = 'lr')
    
    # refit
    _plot_weights(weights_refit,
                  ax,
                  color = refit_color,
                  label = 'refit')
    