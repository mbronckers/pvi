import torch
import numpy as np
import pvi

from .base import ExponentialFamilyDistribution
from pvi.utils.psd_utils import psd_inverse, psd_logdet, safe_psd_inverse


# =============================================================================
# Mean field gaussian distribution
# =============================================================================


class MeanFieldGaussianDistribution(ExponentialFamilyDistribution):
    @property
    def torch_dist_class(self):
        return torch.distributions.Normal

    @property
    def factor_class(self):
        return pvi.distributions.MeanFieldGaussianFactor

    @property
    def batch_dims(self):
        batch_dims = len(self.nat_params["np1"].shape) - 1

        return batch_dims

    def log_a(self, nat_params=None):
        if nat_params is None:
            nat_params = self.nat_params

        np1 = nat_params["np1"]
        np2 = nat_params["np2"]

        if self.batch_dims == 0:
            d = 1
        else:
            d = np1.shape[-1]

        log_a = -0.5 * np.log(np.pi) * d
        log_a += (-(np1 ** 2) / (4 * np2) - 0.5 * (-2 * np2).log()).sum(-1)

        return log_a

    @staticmethod
    def _std_from_unc(unc_params):
        loc = unc_params["loc"]
        log_var = unc_params["log_var"]

        std = {"loc": loc, "scale": torch.exp(log_var) ** 0.5}

        return std

    @staticmethod
    def _unc_from_std(std_params):
        loc = std_params["loc"].detach()
        scale = std_params["scale"].detach()

        unc = {
            "loc": torch.nn.Parameter(loc),
            "log_var": torch.nn.Parameter(2 * torch.log(scale)),
        }

        return unc

    @staticmethod
    def _nat_from_std(std_params):

        loc = std_params["loc"]
        scale = std_params["scale"]

        nat = {"np1": loc * scale ** -2, "np2": -0.5 * scale ** -2}

        return nat

    @staticmethod
    def _std_from_nat(nat_params):

        np1 = nat_params["np1"]
        np2 = nat_params["np2"]

        std = {"loc": -0.5 * np1 / np2, "scale": (-0.5 / np2) ** 0.5}

        return std

    @staticmethod
    def _mean_from_std(std_params):
        loc = std_params["loc"]
        scale = std_params["scale"]

        mp = {
            "m1": loc,
            "m2": scale ** 2 + loc ** 2,
        }

        return mp


# =============================================================================
# Multivariate gaussian distribution
# =============================================================================


class MultivariateGaussianDistribution(ExponentialFamilyDistribution):
    @property
    def torch_dist_class(self):
        return torch.distributions.MultivariateNormal

    @property
    def factor_class(self):
        return pvi.distributions.MultivariateGaussianFactor

    @property
    def batch_dims(self):
        if self._nat_params is not None:
            batch_dims = len(self.nat_params["np1"].shape) - 1
        elif self._unc_params is not None:
            batch_dims = len(self._unc_params["loc"].shape) - 1
        else:
            batch_dims = len(self.std_params["np1"].shape) - 1

        return batch_dims

    def log_a(self, nat_params=None):
        if nat_params is None:
            nat_params = self.nat_params

        np1 = nat_params["np1"]
        np2 = nat_params["np2"]
        cov = psd_inverse(-2 * np2)
        log_a = -0.5 * np.log(np.pi) * np1.shape[-1]
        log_a += 0.25 * np1.unsqueeze(-2).matmul(
            cov.matmul(np1.unsqueeze(-1))
        ).squeeze() - 0.5 * (psd_logdet(-2 * np2))

        return log_a

    @staticmethod
    def _std_from_unc(unc_params):

        loc = unc_params["loc"]
        scale_tril = unc_params["scale_tril"]

        std = {
            "loc": loc,
            "covariance_matrix": scale_tril.matmul(scale_tril.transpose(-1, -2)),
        }

        return std

    @staticmethod
    def _unc_from_std(std_params):

        loc = std_params["loc"].detach()
        cov = std_params["covariance_matrix"].detach()

        scale_tril = torch.cholesky(cov)

        unc = {
            "loc": torch.nn.Parameter(loc),
            "scale_tril": torch.nn.Parameter(scale_tril),
        }

        return unc

    @staticmethod
    def _nat_from_std(std_params):

        loc = std_params["loc"]
        cov = std_params["covariance_matrix"]
        prec = safe_psd_inverse(cov)

        nat = {"np1": prec.matmul(loc.unsqueeze(-1)).squeeze(-1), "np2": -0.5 * prec}

        return nat

    @staticmethod
    def _std_from_nat(nat_params):

        np1 = nat_params["np1"]
        np2 = nat_params["np2"]

        prec = -2.0 * np2
        cov = safe_psd_inverse(prec)

        std = {
            "loc": cov.matmul(np1.unsqueeze(-1)).squeeze(-1),
            "covariance_matrix": cov,
        }

        return std

    @staticmethod
    def _mean_from_std(std_params):
        loc = std_params["loc"]
        cov = std_params["covariance_matrix"]

        mp = {
            "m1": loc,
            "m2": cov + loc.unsqueeze(-1).matmul(loc.unsqueeze(-2)),
        }

        return mp


# =============================================================================
# Dirichlet distribution
# =============================================================================


class DirichletDistribution(ExponentialFamilyDistribution):
    @property
    def torch_dist_class(self):
        return torch.distributions.Dirichlet

    @property
    def factor_class(self):
        return pvi.distributions.DirichletFactor

    @property
    def batch_dims(self):
        batch_dims = len(self.nat_params["np1"].shape) - 1

        return batch_dims

    def log_a(self, nat_params=None):
        if nat_params is None:
            nat_params = self.nat_params

        np1 = nat_params["np1"]
        conc = np1 + 1.0
        log_a = torch.lgamma(conc).sum(-1)
        log_a -= torch.lgamma(conc.sum(-1))

        return log_a

    @staticmethod
    def _std_from_unc(unc_params):

        log_conc = unc_params["up1"]

        std = {"concentration": torch.exp(log_conc)}

        return std

    @staticmethod
    def _unc_from_std(std_params):

        conc = std_params["concentration"].detach()
        log_conc = torch.log(conc)

        unc = {"up1": torch.nn.Parameter(log_conc)}

        return unc

    @staticmethod
    def _nat_from_std(std_params):

        conc = std_params["concentration"]

        nat = {"np1": conc - 1.0}

        return nat

    @staticmethod
    def _std_from_nat(nat_params):

        conc_minus_one = nat_params["np1"]

        std = {"concentration": conc_minus_one + 1.0}

        return std

    @staticmethod
    def _mean_from_std(std_params):
        conc = std_params["concentration"]

        mp = {"m1": torch.digamma(conc) - torch.digamma(conc.sum(-1))}

        return mp


# =============================================================================
# Multinomial distribution
# =============================================================================


class MultinomialDistribution(ExponentialFamilyDistribution):
    @property
    def mean_params(self):
        raise NotImplementedError

    @staticmethod
    def _std_from_unc(unc_params):

        # First parameter is the number of trials and therefore not learnable
        up1 = unc_params["up1"]
        up2 = unc_params["up2"]

        p = torch.exp(up2)
        p = p / p.sum()

        std = {
            "total_count": up1,
            "probs": p,
        }

        return std

    @staticmethod
    def _unc_from_std(std_params):

        # First parameter is the number of trials and therefore not learnable
        sp1 = std_params["total_count"]
        sp2 = std_params["probs"]

        n = sp1
        log_p = torch.log(sp2)

        unc = {
            "up1": torch.nn.Parameter(n, requires_grad=False).int(),
            "up2": torch.nn.Parameter(log_p),
        }

        return unc

    @staticmethod
    def _nat_from_std(std_params):

        # First parameter is the number of trials and therefore not learnable
        sp1 = std_params["total_count"]
        sp2 = std_params["probs"]

        log_p = torch.log(sp2)

        nat = {
            "np1": sp1,
            "np2": log_p,
        }

        return nat

    @staticmethod
    def _std_from_nat(nat_params):

        np1 = nat_params["np1"]
        np2 = nat_params["np2"]

        p = torch.exp(np2)
        p = p / p.sum()

        std = {"total_count": np1, "probs": p}

        return std

    @staticmethod
    def _mean_from_std(std_params):
        raise NotImplementedError

    @property
    def torch_dist_class(self):
        return torch.distributions.Multinomial

    @property
    def factor_class(self):
        return pvi.distributions.MultinomialFactor


# =============================================================================
# Gamma distribution
# =============================================================================


class GammaDistribution(ExponentialFamilyDistribution):
    @property
    def mean_params(self):
        raise NotImplementedError

    @staticmethod
    def _std_from_unc(unc_params):
        log_alpha = unc_params["log_alpha"]
        log_beta = unc_params["log_beta"]

        concentration = log_alpha.exp()
        rate = 1 / log_beta.exp()

        std = {"concentration": concentration, "rate": rate}

        return std

    @staticmethod
    def _unc_from_std(std_params):
        concentration = std_params["concentration"].detach()
        rate = std_params["rate"].detach()

        unc = {
            "log_alpha": torch.nn.Parameter(concentration.log()),
            "log_beta": torch.nn.Parameter((1 / rate).log()),
        }

        return unc

    @staticmethod
    def _nat_from_std(std_params):
        concentration = std_params["concentration"]
        rate = std_params["rate"]

        np1 = concentration - 1
        np2 = -1 / rate

        nat = {
            "np1": np1,
            "np2": np2,
        }

        return nat

    @staticmethod
    def _std_from_nat(nat_params):
        np1 = nat_params["np1"]
        np2 = nat_params["np2"]

        concentration = np1 + 1
        rate = -1 / np2

        std = {"concentration": concentration, "rate": rate}

        return std

    @staticmethod
    def _mean_from_std(std_params):
        raise NotImplementedError

    @property
    def torch_dist_class(self):
        return torch.distributions.Gamma

    @property
    def factor_class(self):
        return pvi.distributions.GammaFactor


# =============================================================================
# Log-Normal distributions
# =============================================================================


class LogNormalDistribution(MeanFieldGaussianDistribution):
    @property
    def torch_dist_class(self):
        return torch.distributions.LogNormal

    @property
    def factor_class(self):
        return pvi.distributions.LogNormalFactor


# =============================================================================
# Categorical distribution
# =============================================================================


class CategoricalDistribution(ExponentialFamilyDistribution):
    @property
    def torch_dist_class(self):
        return torch.distributions.Categorical

    @property
    def factor_class(self):
        return pvi.distributions.CategoricalFactor

    @property
    def batch_dims(self):
        batch_dims = len(self.nat_params["np1"].shape) - 1

        return batch_dims

    def log_a(self, nat_params=None):
        return 0

    @ExponentialFamilyDistribution.std_params.setter
    def std_params(self, std_params):
        std_params["probs"] = std_params["probs"] / std_params["probs"].sum(
            -1
        ).unsqueeze(-1)

        ExponentialFamilyDistribution.std_params.fset(self, std_params)

    @ExponentialFamilyDistribution.nat_params.setter
    def nat_params(self, nat_params):
        log_p = nat_params["log_probs"]
        p = log_p.exp()
        p = p / p.sum(-1).unsqueeze(-1)
        nat_params["log_probs"] = p.log()

        ExponentialFamilyDistribution.nat_params.fset(self, nat_params)

    @staticmethod
    def _std_from_unc(unc_params):
        log_p = unc_params["log_probs"]
        p = log_p.exp()
        p = p / p.sum(-1).unsqueeze(-1)

        std = {"probs": p}

        return std

    @staticmethod
    def _unc_from_std(std_params):
        p = std_params["probs"].detach()

        unc = {
            "log_probs": torch.nn.Parameter(p.log()),
        }

        return unc

    @staticmethod
    def _nat_from_std(std_params):
        p = std_params["probs"]

        nat = {"log_probs": torch.log(p)}

        return nat

    @staticmethod
    def _std_from_nat(nat_params):
        log_p = nat_params["log_probs"]

        std = {
            "probs": log_p.exp(),
        }

        return std

    @staticmethod
    def _mean_from_std(std_params):
        p = std_params["probs"]

        mp = {
            "probs": p,
        }

        return mp


# =============================================================================
# Beta distribution
# =============================================================================


class BetaDistribution(ExponentialFamilyDistribution):
    @property
    def torch_dist_class(self):
        return torch.distributions.Beta

    @property
    def factor_class(self):
        return pvi.distributions.BetaFactor

    @property
    def batch_dims(self):
        batch_dims = len(self.nat_params["np1"].shape) - 1

        return batch_dims

    def log_a(self, nat_params=None):
        if nat_params is None:
            nat_params = self.nat_params

        np1 = nat_params["np1"]
        np2 = nat_params["np2"]

        log_a = (
            torch.lgamma(np1 + 1) + torch.lgamma(np2 + 1) - torch.lgamma(np1 + np2 + 2)
        ).sum(-1)

        return log_a

    @staticmethod
    def _std_from_unc(unc_params):
        log_alpha = unc_params["log_alpha"]
        log_beta = unc_params["log_beta"]

        std = {"concentration1": log_alpha.exp(), "concentration0": log_beta.exp()}

        return std

    @staticmethod
    def _unc_from_std(std_params):
        alpha = std_params["concentration1"]
        beta = std_params["concentration0"]

        unc = {
            "log_alpha": torch.nn.Parameter(alpha.log()),
            "log_beta": torch.nn.Parameter(beta.log()),
        }

        return unc

    @staticmethod
    def _nat_from_std(std_params):
        alpha = std_params["concentration1"]
        beta = std_params["concentration0"]

        nat = {"np1": alpha - 1, "np2": beta - 1}

        return nat

    @staticmethod
    def _std_from_nat(nat_params):
        np1 = nat_params["np1"]
        np2 = nat_params["np2"]

        std = {"concentration1": np1 + 1, "concentration0": np2 + 2}

        return std

    @staticmethod
    def _mean_from_std(std_params):
        alpha = std_params["concentration1"]
        beta = std_params["concentration0"]

        mp = {
            "m1": torch.digamma(alpha) - torch.digamma(alpha + beta),
            "m2": torch.digamma(beta) - torch.digamma(alpha + beta),
        }

        return mp
