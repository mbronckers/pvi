from abc import ABC, abstractmethod


class Model(ABC):
    """
    An abstract class for probabilistic models defined by a likelihood
    p(y | θ, x) and (approximate) posterior q(θ).
    """
    def __init__(self, hyperparameters=None, config=None):
        # Configuration of the model.
        if config is None:
            config = {}

        self._config = self.get_default_config()
        self.config = config

        # Hyper-parameters of the model.
        if hyperparameters is None:
            hyperparameters = {}

        self._hyperparameters = self.get_default_hyperparameters()
        self.hyperparameters = hyperparameters

    @abstractmethod
    def get_default_nat_params(self):
        """
        :return: A default set of natural parameters for the prior.
        """
        raise NotImplementedError

    @property
    def config(self):
        return self._config

    @config.setter
    def config(self, config):
        self._config = {**self._config, **config}

    @abstractmethod
    def get_default_config(self):
        """
        :return: A default set of config for the model.
        """
        raise NotImplementedError

    @property
    def hyperparameters(self):
        return self._hyperparameters

    @hyperparameters.setter
    def hyperparameters(self, hyperparameters):
        self._hyperparameters = {**self._hyperparameters, **hyperparameters}

    @abstractmethod
    def get_default_hyperparameters(self):
        """
        :return: A default set of parameters for the model.
        """
        raise NotImplementedError

    @abstractmethod
    def forward(self, x, q):
        """
        Returns the (approximate) predictive posterior.
        :param x: The input locations to make predictions at.
        :param q: The approximate posterior distribution q(θ).
        :return: ∫ p(y | θ, x) q(θ) dθ.
        """
        raise NotImplementedError

    @abstractmethod
    def likelihood_forward(self, x, theta):
        """
        Returns the model's likelihood p(y | θ, x).
        :param x: The input locations to make predictions at.
        :param theta: The latent variables of the model.
        :return: p(y | θ, x)
        """
        raise NotImplementedError

    def likelihood_log_prob(self, data, theta):
        """
        Compute the log probability of the data under the model's likelihood.
        :param data: The data to compute the log likelihood of.
        :param theta: The latent variables of the model.
        :return: log p(y | x, θ)
        """
        dist = self.likelihood_forward(data["x"], theta)
        return dist.log_prob(data["y"])

    @abstractmethod
    def conjugate_update(self, data, q, t=None):
        """
        If the likelihood is conjugate with q(θ), performs a conjugate update.
        :param data: The data to compute the conjugate update with.
        :param q: The current global posterior q(θ).
        :param t: The local factor t(θ).
        :return: The updated posterior, p(θ | data).
        """
        raise NotImplementedError

    @abstractmethod
    def expected_log_likelihood(self, data, q):
        """
        Computes the expected log likelihood of the data under q(θ).
        :param data: The data to compute the conjugate update with.
        :param q: The current global posterior q(θ).
        :return: ∫ q(θ) log p(y | x, θ) dθ.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def conjugate_family(self):
        raise NotImplementedError
