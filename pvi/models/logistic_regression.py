import torch
import numpy as np

from torch import distributions, nn, optim
from .base import Model
from pvi.distributions.exponential_family_distributions import (
    MultivariateGaussianDistribution,
)


class LogisticRegressionModel(Model, nn.Module):
    """
    Logistic regression model with a multivariate Gaussian approximate
    posterior.
    """

    conjugate_family = None

    def __init__(self, include_bias=True, **kwargs):
        self.include_bias = include_bias

        Model.__init__(self, **kwargs)
        nn.Module.__init__(self)

    def get_default_nat_params(self):
        if self.include_bias:
            return {
                "np1": torch.tensor([0.0] * (self.config["D"] + 1)),
                "np2": torch.tensor([1.0] * (self.config["D"] + 1)).diag_embed(),
            }
        else:
            return {
                "np1": torch.tensor([0.0] * self.config["D"]),
                "np2": torch.tensor([1.0] * self.config["D"]).diag_embed(),
            }

    def get_default_config(self):
        return {
            "D": None,
            "optimiser_class": optim.Adam,
            "optimiser_params": {"lr": 1e-3},
            "reset_optimiser": True,
            "epochs": 100,
            "batch_size": 100,
            "num_elbo_samples": 1,
            "num_predictive_samples": 1,
            "print_epochs": 10,
            "use_probit_approximation": True,
        }

    def get_default_hyperparameters(self):
        """
        :return: A default set of ε for the model.
        """
        return {}

    def forward(self, x, q, **kwargs):
        """
        Returns the (approximate) predictive posterior distribution of a
        Bayesian logistic regression model.
        :param x: The input locations to make predictions at.
        :param q: The approximate posterior distribution q(θ).
        :return: ∫ p(y | θ, x) q(θ) dθ ≅ (1/M) Σ_m p(y | θ_m, x) θ_m ~ q(θ).
        """
        if self.config["use_probit_approximation"]:
            # Use Probit approximation.

            if self.include_bias:
                x_ = torch.cat((x, torch.ones(len(x)).to(x).unsqueeze(-1)), dim=1)
            else:
                x_ = x

            q_loc = q.std_params["loc"]
            if isinstance(q.distribution, distributions.MultivariateNormal):
                q_cov = q.std_params["covariance_matrix"]
            elif isinstance(q.distribution, distributions.Normal):
                q_scale = q.std_params["scale"]
                q_cov = q_scale.diag_embed() ** 2

            for _ in range(len(q_loc.shape) - 1):
                x_ = x_.unsqueeze(0)

            # (*, N, D, 1).
            x_ = x_.unsqueeze(-1)

            # (*, 1, D).
            q_loc = q_loc.unsqueeze(-2)

            # (*, 1, D, D).
            q_cov = q_cov.unsqueeze(-3)

            # (*, N).
            denom = (
                x_.transpose(-1, -2)
                .matmul(q_cov)
                .matmul(x_)
                .reshape(*q_loc.shape[:-2], -1)
            )
            denom = (1 + np.pi * denom / 8) ** 0.5
            logits = (
                q_loc.unsqueeze(-2).matmul(x_).reshape(*q_loc.shape[:-2], -1) / denom
            )

            # batch_shape = (*, N).
            dist = distributions.Bernoulli(logits=logits)
            return dist

        else:
            thetas = q.distribution.sample((self.config["num_predictive_samples"],))
            return self.likelihood_forward(x, thetas)

    def likelihood_forward(self, x, theta, **kwargs):
        """
        Returns the model's likelihood p(y | θ, x).
        :param x: Input of shape (N, D).
        :param theta: Parameters of shape (*, D + 1).
        :return: Bernoulli distribution.
        """
        assert len(x.shape) == 2, "x must be (N, D)."
        assert len(theta.shape) > 1, "θ must have at least one batch dimension."
        assert theta.shape[-1] == (x.shape[-1] + self.include_bias)

        if self.include_bias:
            x_ = torch.cat((x, torch.ones(len(x)).to(x).unsqueeze(-1)), dim=1)
        else:
            x_ = x

        if len(x.shape) == 1:
            x_r = x_.unsqueeze(0).repeat(len(theta), 1)
            logits = x_r.unsqueeze(-2).matmul(theta.unsqueeze(-1)).reshape(-1)
        else:
            for _ in range(len(theta.shape) - 1):
                x_ = x_.unsqueeze(0)
            # (*, N, 1, D).
            x_ = x_.unsqueeze(-2)

            # (*, 1, D, 1).
            theta = theta.unsqueeze(-2).unsqueeze(-1)

            logits = x_.matmul(theta).squeeze(-1).squeeze(-1)

        return distributions.Bernoulli(logits=logits)

    def conjugate_update(self, data, q, t=None):
        """
        :param data: The local data to refine the model with.
        :param q: The current global posterior q(θ).
        :param t: The the local factor t(θ).
        :return: q_new, t_new, the new global posterior and the new local
        contribution.
        """
        raise NotImplementedError


class MulticlassLogisticRegressionModel(Model, nn.Module):
    """
    Multiclass logistic regression model with a multivariate Gaussian approximate
    posterior.
    """

    conjugate_family = None

    def __init__(self, include_bias=True, **kwargs):
        self.include_bias = include_bias

        Model.__init__(self, **kwargs)
        nn.Module.__init__(self)

    def get_default_nat_params(self):
        return {
            "np1": torch.zeros((self.config["P"], self.config["D"] + self.include_bias)),
            "np2": torch.ones((self.config["P"], self.config["D"] + self.include_bias)).diag_embed(),
        }

    def get_default_config(self):
        return {
            "D": None,
            "P": 1,
            "optimiser_class": optim.Adam,
            "optimiser_params": {"lr": 1e-3},
            "reset_optimiser": True,
            "epochs": 100,
            "batch_size": 100,
            "num_elbo_samples": 1,
            "num_predictive_samples": 1,
            "print_epochs": 10,
        }

    def get_default_hyperparameters(self):
        """
        :return: A default set of ε for the model.
        """
        return {}

    def forward(self, x, q, num_samples=None, **kwargs):
        """
        Returns the (approximate) predictive posterior distribution of a
        Bayesian logistic regression model.
        :param x: The input locations to make predictions at.
        :param q: The approximate posterior distribution q(θ).
        :return: ∫ p(y | θ, x) q(θ) dθ ≅ (1/M) Σ_m p(y | θ_m, x) θ_m ~ q(θ).
        """
        if num_samples is None:
            thetas = q.distribution.sample((self.config["num_predictive_samples"],))
        else:
            thetas = q.distribution.sample((num_samples,))
            
        return self.likelihood_forward(x, thetas)

    def likelihood_forward(self, x, theta, **kwargs):
        """
        Returns the model's likelihood p(y | θ, x).
        :param x: Input of shape (N, D).
        :param theta: Parameters of shape (*, P, D + 1).
        :return: Bernoulli distribution.
        """
        assert len(x.shape) == 2, "x must be (N, D)."
        assert len(theta.shape) > 2, "θ must have at least one batch dimension."
        assert theta.shape[-1] == (x.shape[-1] + self.include_bias)

        if self.include_bias:
            x_ = torch.cat((x, torch.ones(len(x)).to(x).unsqueeze(-1)), dim=1)
        else:
            x_ = x

        for _ in range(len(theta.shape) - 2):
            x_ = x_.unsqueeze(0)
            
        # (*, N, P).
        logits = x_.matmul(theta.transpose(-1, -2))
        return distributions.Categorical(logits=logits)

    def conjugate_update(self, data, q, t=None):
        """
        :param data: The local data to refine the model with.
        :param q: The current global posterior q(θ).
        :param t: The the local factor t(θ).
        :return: q_new, t_new, the new global posterior and the new local
        contribution.
        """
        raise NotImplementedError
