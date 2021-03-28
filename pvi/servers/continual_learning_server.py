import logging

from .base import Server

logger = logging.getLogger(__name__)


class ContinualLearningServer(Server):
    def __init__(self, model, q, clients, hyperparameters=None):
        super().__init__(model, q, clients, hyperparameters)

        # Loop through each client just once.
        self.set_hyperparameters({"max_iterations": len(self.clients)})

        self.client_idx = 0
        self.log["q"].append(self.q.non_trainable_copy())
        self.log["communications"].append(self.communications)

    def get_default_hyperparameters(self):
        return {
            **super().get_default_hyperparameters(),
        }

    def tick(self):
        if self.should_stop():
            return False

        logger.debug("Getting client updates.")

        client = self.clients[self.client_idx]

        if client.can_update():
            q_new = client.fit(self.q)
            self.q = q_new.non_trainable_copy()

            self.communications += 1

            self.log["q"].append(self.q.non_trainable_copy())
            self.log["communications"].append(self.communications)

        logger.debug(f"Iteration {self.iterations} complete."
                     f"\nNew natural parameters:\n{self.q.nat_params}\n.")

        self.iterations += 1
        self.client_idx = (self.client_idx + 1) % len(self.clients)

    def should_stop(self):
        return self.iterations > self.hyperparameters["max_iterations"] - 1
