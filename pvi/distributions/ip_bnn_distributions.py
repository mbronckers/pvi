import torch

from torch import nn
from pvi.utils.psd_utils import psd_inverse, add_diagonal


class BNNDistribution:
    """
    Maintains a distribution over each layer of a BNN.
    """
    def __init__(self, distributions):

        self.distributions = distributions

    def non_trainable_copy(self):
        distributions = [dist.non_trainable_copy()
                         for dist in self.distributions]

        return type(self)(distributions)

    def trainable_copy(self):
        distributions = [dist.trainable_copy()
                         for dist in self.distributions]

        return type(self)(distributions)

    def compute_dist(self, layer, *args, **kwargs):
        return self.distributions[layer]


class BNNFactor:
    """
    Maintains a pseudo-likelihood factor over each layer of a BNN.
    """
    def __init__(self, distributions, inducing_locations, train_inducing=True):

        self.distributions = distributions
        self.train_inducing = train_inducing

        if inducing_locations is not None:
            self._inducing_locations = nn.Parameter(
                inducing_locations, requires_grad=self.train_inducing)
        else:
            self._inducing_locations = inducing_locations

    @property
    def inducing_locations(self):
        return self._inducing_locations

    @inducing_locations.setter
    def inducing_locations(self, value):
        self._inducing_locations = nn.Parameter(
            value, requires_grad=self.train_inducing)

    def non_trainable_copy(self):
        distributions = [dist.non_trainable_copy()
                         for dist in self.distributions]

        if self._inducing_locations is not None:
            inducing_locations = self.inducing_locations.detach().clone()
        else:
            inducing_locations = None

        return type(self)(
            distributions, inducing_locations,
            train_inducing=self.train_inducing
        )

    def trainable_copy(self):
        distributions = [dist.trainable_copy()
                         for dist in self.distributions]

        if self._inducing_locations is not None:
            inducing_locations = self.inducing_locations.detach().clone()
        else:
            inducing_locations = None

        return type(self)(
            distributions, inducing_locations,
            train_inducing=self.train_inducing
        )

    def parameters(self):
        parameters = [list(dist.parameters()) for dist in self.distributions]
        return [item for sublist in parameters for item in sublist]


class IPBNNGaussianPosterior:
    """
    Maintains the distribution q({w_l}) = p({w_l}) Π t({w_l}).
    """
    def __init__(self, p, ts):
        self.p = p
        self.ts = ts

    @property
    def inducing_locations(self):
        inducing_locations = torch.cat([t.inducing_locations for t in self.ts])
        return inducing_locations

    def form_cavity(self, t):
        """
        Returns the distribution q({w_l}) = p({w_l}) Π _{/ i} t({w_l}).
        :param t: Pseudo-likelihood factor to remove from self.ts.
        :return: q({w_l}) = p({w_l}) Π _{/ i} t({w_l}).
        """
        # Find the pseudo-likelihood factor in self.ts and remove.
        ts = self.ts
        for i, ti in enumerate(self.ts):
            same_inducing = torch.allclose(
                ti.inducing_locations, t.inducing_locations)

            same_np1, same_np2 = [], []
            for ti_dist, t_dist in zip(ti.distributions, t.distributions):
                same_np1.append(torch.allclose(
                    ti_dist.nat_params["np1"], t_dist.nat_params["np1"]))
                same_np2.append(torch.allclose(
                    ti_dist.nat_params["np2"], t_dist.nat_params["np2"]))

            if same_inducing and all(same_np1) and all(same_np2):
                # Set natural parameters to 0. We retain it as need to keep
                # inducing point values.
                for dist in ts[i].distributions:
                    for k, v in dist.nat_params.items():
                        dist.nat_params[k] = torch.zeros_like(v)

                return type(self)(p=self.p, ts=ts), i

        raise ValueError("Could not find t in self.ts!")

    def compute_dist(self, layer, act_z):
        """
        Compute the distribution q(w_l | {w_l}) =
        :param layer: Layer for which to compute the distribution at.
        :param act_z: Post-activation Φ(z), (m, dim_in).
        :return: q(w_l), (dim_out).
        """
        # TODO: this assumes both prior and factors are mean-field.

        # Get IP means and variances for layer. Each t_dist maintains a
        # distribution with dimension (mi, dim_out).
        t_dists = [t.distributions[layer] for t in self.ts]
        p_dist = self.p.distributions[layer]

        # (m, dim_out).
        t_np1 = torch.cat([dist.nat_params["np1"] for dist in t_dists], dim=0)
        t_np2 = torch.cat([dist.nat_params["np2"] for dist in t_dists], dim=0)

        # (dim_out, m).
        t_np1 = t_np1.transpose(0, 1)
        t_np2 = t_np2.transpose(0, 1)

        # (dim_out, m, m).
        t_np2 = t_np2.diag_embed()

        num_samples, dim_in, m = act_z.shape
        dim_out = t_np1.shape[0]

        # (num_samples, dim_out, m, dim_in).
        act_z_ = act_z.unsqueeze(1).repeat(1, dim_out, 1, 1)
        # (num_samples, dim_out, m).
        t_np1_ = t_np1.unsqueeze(0).repeat(num_samples, 1, 1)
        # (num_samples, dim_out, dim_in, 1)
        np1 = act_z_.transpose(-1, -2).matmul(t_np1_.unsqueeze(-1))

        # (num_samples, dim_out, m, m).
        t_np2_ = t_np2.unsqueeze(0).repeat(num_samples, 1, 1, 1)
        # (m, m).
        p_np2 = p_dist.nat_params["np2"].diag_embed()
        # (num_samples, dim_out, dim_in, dim_in).
        np2 = p_np2 + act_z_.transpose(-1, -2).matmul(t_np2_).matmul(act_z_)

        # Compute mean and covariance matrix for each column of weights.
        prec = -2. * np2
        cov = psd_inverse(prec)  # (num_samples, dim_out, dim_in, dim_in)
        loc = cov.matmul(np1).squeeze()  # (num_samples, dim_out, dim_in)
        qw = torch.distributions.MultivariateNormal(loc, cov)

        return qw

    def non_trainable_copy(self):
        return type(self)(
            p=self.p.non_trainable_copy(),
            ts=[t.non_trainable_copy() for t in self.ts],
        )

    def trainable_copy(self):
        # TODO: Never train prior distribution??
        return type(self)(
            p=self.p.non_trainable_copy(),
            ts=[t.trainable_copy() for t in self.ts],
        )

    def replace_factor(self, t_old, t_new, **kwargs):
        """
        Forms a new distribution by replacing t_old(θ) with t_new(θ).
        :param t_old: The factor to remove.
        :param t_new: The factor to add.
        :param kwargs: Passed to self.create_new()
        :return: Updated distribution.
        """
        # Find location of old factor and replace.
        q, t_idx = self.form_cavity(t_old)
        q.ts[t_idx] = t_new

        return q

    def parameters(self):
        parameters = [t.parameters() for t in self.ts]
        return [item for sublist in parameters for item in sublist]