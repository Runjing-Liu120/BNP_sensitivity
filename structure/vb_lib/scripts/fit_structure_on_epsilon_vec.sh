sbatch --array 0-10 --export=perturbation='worst_case' fit_structure_on_epsilon.sh

# sbatch --array 0-10 --export=perturbation='sigmoidal' fit_structure_on_epsilon.sh
# sbatch --array 0-10 --export=perturbation='sigmoidal_neg' fit_structure_on_epsilon.sh

# sbatch --array 0-10 --export=perturbation='alpha_pert_pos' fit_structure_on_epsilon.sh
# sbatch --array 0-10 --export=perturbation='alpha_pert_neg' fit_structure_on_epsilon.sh
