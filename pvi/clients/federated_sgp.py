import logging
import torch

from .base import Client
from pvi.utils.psd_utils import psd_inverse
from pvi.utils.gaussian import joint_from_marginal
from torch.utils.data import TensorDataset, DataLoader
from tqdm.auto import tqdm

logger = logging.getLogger(__name__)


class FederatedSGPClient(Client):
    def __init__(self, data, model, t, config=None):
        super().__init__(data, model, t, config)

    def gradient_based_update(self, q):
        # TODO: use the collapsed variational lower bound for SGP regression.
        # Cannot update during optimisation.
        self._can_update = False

        # Check server has marginalised properly.
        assert torch.allclose(q.inducing_locations.detach(),
                              self.t.inducing_locations), \
            "Inducing location of q and self.t do not match."

        # Copy the approximate posterior, make old posterior non-trainable.
        q_cav = q.non_trainable_copy()
        q_cav.nat_params = {k: v - self.t.nat_params[k]
                            for k, v in q_cav.nat_params.items()}

        # Parameters are those of q(θ) and self.model.
        if self.config["train_model"]:
            parameters = [
                {"params": q.parameters()},
                {"params": self.model.parameters(),
                 **self.config["model_optimiser_params"]}
            ]
        else:
            parameters = q.parameters()

        # Reset optimiser.
        logging.info("Resetting optimiser")
        optimiser = getattr(torch.optim, self.config["optimiser"])(
            parameters, **self.config["optimiser_params"])

        # Set up data
        x = self.data["x"]
        y = self.data["y"]

        tensor_dataset = TensorDataset(x, y)
        loader = DataLoader(tensor_dataset,
                            batch_size=self.config["batch_size"],
                            shuffle=True)

        # Dict for logging optimisation progress
        training_curve = {
            "elbo": [],
            "kl": [],
            "ll": [],
            "logt": [],
        }

        # Stay fixed throughout optimisation.
        za = q_cav.inducing_locations
        kaa = self.model.kernel(za, za).evaluate().detach()
        ikaa = psd_inverse(kaa)

        # Compute joint distributions q(a, b) and qcav(a, b).
        zb = q.inducing_locations
        z = torch.cat([za, zb], axis=0)

        kab = self.model.kernel(za, zb).evaluate()
        kbb = self.model.kernel(zb, zb).evaluate()
        ikbb = psd_inverse(kbb)

        qab_loc, qab_cov = joint_from_marginal(q, kab.T, ikaa=ikbb)
        qab_cav_loc, qab_cav_cov = joint_from_marginal(
            q_cav, kab, ikaa=ikaa)

        qab = type(q)(
            inducing_locations=z,
            std_params={
                "loc": qab_loc,
                "covariance_matrix": qab_cov,
            }
        )

        qab_cav = type(q)(
            inducing_locations=z,
            std_params={
                "loc": qab_cav_loc,
                "covariance_matrix": qab_cav_cov,
            }
        )

        # Gradient-based optimisation loop -- loop over epochs
        epoch_iter = tqdm(range(self.config["epochs"]), desc="Epoch",
                          leave=True)
        # for i in range(self.config["epochs"]):
        for i in epoch_iter:
            epoch = {
                "elbo": 0,
                "kl": 0,
                "ll": 0,
                "logt": 0,
            }

            # Loop over batches in current epoch
            for (x_batch, y_batch) in iter(loader):
                optimiser.zero_grad()

                batch = {
                    "x": x_batch,
                    "y": y_batch,
                }

                # Compute KL divergence between q and q_old.
                # kl = q.kl_divergence(q_old).sum() / len(x).

                kl = qab.kl_divergence(qab_cov).sum() / len(x)

                # Sample θ from q and compute p(y | θ, x) for each θ
                ll = self.model.expected_log_likelihood(
                    batch, q, self.config["num_elbo_samples"]).sum()
                ll /= len(x_batch)

                loss = kl - ll
                loss.backward()
                optimiser.step()

                # Recompute joint distributions q(a, b) and qcav(a, b).
                zb = q.inducing_locations
                z = torch.cat([za, zb], axis=0)

                kab = self.model.kernel(za, zb).evaluate()
                kbb = self.model.kernel(zb, zb).evaluate()
                ikbb = psd_inverse(kbb)

                qab_loc, qab_cov = joint_from_marginal(q, kab.T, ikaa=ikbb)
                qab_cav_loc, qab_cav_cov = joint_from_marginal(
                    q_cav, kab, ikaa=ikaa)

                qab = type(q)(
                    inducing_locations=z,
                    std_params={
                        "loc": qab_loc,
                        "covariance_matrix": qab_cov,
                    }
                )

                qab_cav = type(q)(
                    inducing_locations=z,
                    std_params={
                        "loc": qab_cav_loc,
                        "covariance_matrix": qab_cav_cov,
                    }
                )

                # Keep track of quantities for current batch
                # Will be very slow if training on GPUs.
                epoch["elbo"] += -loss.item() / len(loader)
                epoch["kl"] += kl.item() / len(loader)
                epoch["ll"] += ll.item() / len(loader)

            # Log progress for current epoch
            training_curve["elbo"].append(epoch["elbo"])
            training_curve["kl"].append(epoch["kl"])
            training_curve["ll"].append(epoch["ll"])

            if self.t is not None:
                training_curve["logt"].append(epoch["logt"])

            if i % self.config["print_epochs"] == 0:
                logger.debug(f"ELBO: {epoch['elbo']:.3f}, "
                             f"LL: {epoch['ll']:.3f}, "
                             f"KL: {epoch['kl']:.3f}, "
                             f"log t: {epoch['logt']:.3f}, "
                             f"Epochs: {i}.")

            epoch_iter.set_postfix(elbo=epoch["elbo"], kl=epoch["kl"],
                                   ll=epoch["ll"], logt=epoch["logt"])

        # Log the training curves for this update
        self.log["training_curves"].append(training_curve)

        # Create non-trainable copy to send back to server.
        q_new = q.non_trainable_copy()

        # Finished optimisation, can now update.
        self._can_update = True

        # Compute new local contribution from old distributions.
        # t(b) = ∫ (q(a, b) / q_cav(a, b)) da

        # TODO: apply damped local updates.

        # First compute t(a, b) = [q(a, b) / q_old(a, b)] * t_old(a).
        tab_np = {k: (v.detach() - qab_cav.nat_params[k].detach())
                  for k, v in qab.nat_params.items()}

        # Convert to std params and extract those for t(b) then back to nat
        # params.
        tab_std = q._std_from_nat(tab_np)
        tb_std = {
            "loc": tab_std["loc"][len(za):],
            "covariance_matrix": tab_std["covariance_matrix"][
                                 len(za):, len(za):],
        }
        tb_np = q._nat_from_std(tb_std)
        t_new = type(self.t)(
            inducing_locations=zb.detach(),
            nat_params=tb_np,
        )

        return q_new, t_new
