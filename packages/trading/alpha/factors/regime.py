"""
Regime Detection Module
Detects market regimes: trend, mean-reversion, volatile using HMM and volatility clustering
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Literal
from dataclasses import dataclass
from enum import Enum
import logging
from scipy.stats import norm
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


class RegimeType(Enum):
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    MEAN_REVERSION = "mean_reversion"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


@dataclass
class RegimeState:
    """Represents a detected market regime state"""
    regime: RegimeType
    confidence: float
    start_idx: int
    end_idx: Optional[int]
    params: Dict  # regime-specific parameters


class VolatilityRegimeDetector:
    """
    Volatility-based regime detection using rolling statistics and clustering.
    Fast, no external dependencies beyond numpy/scipy.
    """
    
    def __init__(
        self,
        window: int = 60,
        n_regimes: int = 3,
        vol_threshold_low: float = 0.01,
        vol_threshold_high: float = 0.03,
    ):
        self.window = window
        self.n_regimes = n_regimes
        self.vol_threshold_low = vol_threshold_low
        self.vol_threshold_high = vol_threshold_high
    
    def detect(self, returns: pd.Series) -> List[RegimeState]:
        """Detect regimes from return series"""
        if len(returns) < self.window * 2:
            return [RegimeState(RegimeType.UNKNOWN, 0.0, 0, None, {})]
        
        # Rolling volatility
        rolling_vol = returns.rolling(self.window).std()
        rolling_mean = returns.rolling(self.window).mean()
        rolling_skew = returns.rolling(self.window).skew()
        
        # Features for regime classification
        features = pd.DataFrame({
            'vol': rolling_vol,
            'mean': rolling_mean,
            'skew': rolling_skew,
            'vol_ratio': rolling_vol / rolling_vol.rolling(self.window).mean(),
        }).dropna()
        
        regimes = []
        current_regime = None
        start_idx = 0
        
        for idx, row in features.iterrows():
            regime = self._classify_regime(row['vol'], row['mean'], row['skew'], row['vol_ratio'])
            
            if regime != current_regime:
                if current_regime is not None:
                    regimes.append(RegimeState(
                        regime=current_regime,
                        confidence=self._compute_confidence(row),
                        start_idx=start_idx,
                        end_idx=idx,
                        params={'vol': row['vol'], 'mean': row['mean'], 'skew': row['skew']}
                    ))
                current_regime = regime
                start_idx = idx
        
        # Close last regime
        if current_regime is not None:
            regimes.append(RegimeState(
                regime=current_regime,
                confidence=self._compute_confidence(features.iloc[-1]),
                start_idx=start_idx,
                end_idx=None,
                params={'vol': features.iloc[-1]['vol'], 'mean': features.iloc[-1]['mean'], 'skew': features.iloc[-1]['skew']}
            ))
        
        return regimes
    
    def _classify_regime(self, vol: float, mean: float, skew: float, vol_ratio: float) -> RegimeType:
        """Classify regime based on volatility and return characteristics"""
        sharpe = abs(mean) / vol if vol > 0 else 0
        # Annualized return threshold (approx 10% annual = 0.04% daily)
        trend_threshold = 0.0004
        
        if vol > self.vol_threshold_high:
            # High volatility regime
            if abs(mean) > trend_threshold and sharpe > 0.3:
                return RegimeType.TREND_UP if mean > 0 else RegimeType.TREND_DOWN
            return RegimeType.VOLATILE
        elif vol < self.vol_threshold_low:
            # Low volatility - check if trending or mean reverting
            if abs(mean) > trend_threshold and sharpe > 0.5:
                return RegimeType.TREND_UP if mean > 0 else RegimeType.TREND_DOWN
            return RegimeType.MEAN_REVERSION
        else:
            # Medium volatility
            if abs(mean) > trend_threshold and sharpe > 0.8:
                return RegimeType.TREND_UP if mean > 0 else RegimeType.TREND_DOWN
            return RegimeType.MEAN_REVERSION
    
    def _compute_confidence(self, row: pd.Series) -> float:
        """Compute confidence score for regime classification"""
        vol = row['vol']
        mean = row['mean']
        sharpe = abs(mean) / vol if vol > 0 else 0
        # Higher confidence for clear trend (high Sharpe) or clear low vol
        if sharpe > 1.5:
            return min(0.95, 0.5 + sharpe * 0.2)
        elif vol < self.vol_threshold_low:
            return 0.8
        elif vol > self.vol_threshold_high:
            return 0.7
        return 0.5


class HMMRegimeDetector:
    """
    Hidden Markov Model regime detection.
    Models returns as mixture of Gaussian distributions with regime-dependent params.
    """
    
    def __init__(self, n_states: int = 3, max_iter: int = 100, tol: float = 1e-4, 
                 self_transition_prob: float = 0.99):
        self.n_states = n_states
        self.max_iter = max_iter
        self.tol = tol
        self.self_transition_prob = self_transition_prob
        self.transition_matrix_ = None
        self.emission_means_ = None
        self.emission_vars_ = None
        self.initial_probs_ = None
    
    def fit(self, returns: np.ndarray) -> 'HMMRegimeDetector':
        """Fit HMM using Baum-Welch (EM algorithm)"""
        T = len(returns)
        
        # Initialize parameters
        self._initialize_params(returns)
        
        log_likelihood_old = -np.inf
        
        for iteration in range(self.max_iter):
            # E-step: Forward-Backward algorithm
            alpha, log_likelihood = self._forward(returns)
            beta = self._backward(returns)
            gamma = self._compute_gamma(alpha, beta)
            xi = self._compute_xi(returns, alpha, beta)
            
            # M-step: Update parameters
            self._update_params(returns, gamma, xi)
            
            # Check convergence
            if abs(log_likelihood - log_likelihood_old) < self.tol:
                logger.debug(f"HMM converged after {iteration + 1} iterations, LL={log_likelihood:.4f}")
                break
            log_likelihood_old = log_likelihood
        
        return self
    
    def _initialize_params(self, returns: np.ndarray):
        """Initialize HMM parameters using k-means on returns"""
        from scipy.cluster.vq import kmeans2
        
        # Simple initialization
        self.initial_probs_ = np.ones(self.n_states) / self.n_states
        
        # Transition matrix with high self-transition probability for regime persistence
        self.transition_matrix_ = np.full((self.n_states, self.n_states), 
                                           (1 - self.self_transition_prob) / (self.n_states - 1))
        np.fill_diagonal(self.transition_matrix_, self.self_transition_prob)
        
        # Use k-means for initial emission params
        centroids, labels = kmeans2(returns.reshape(-1, 1), self.n_states, minit='points')
        self.emission_means_ = centroids.flatten()
        self.emission_vars_ = np.array([
            np.var(returns[labels == i]) if np.sum(labels == i) > 1 else np.var(returns)
            for i in range(self.n_states)
        ])
        # Ensure positive variance
        self.emission_vars_ = np.maximum(self.emission_vars_, 1e-6)
    
    def _forward(self, returns: np.ndarray) -> Tuple[np.ndarray, float]:
        """Forward algorithm"""
        T = len(returns)
        alpha = np.zeros((T, self.n_states))
        
        # Initial
        for i in range(self.n_states):
            alpha[0, i] = self.initial_probs_[i] * self._emission_prob(returns[0], i)
        alpha[0] /= alpha[0].sum()
        
        # Recursion
        for t in range(1, T):
            for j in range(self.n_states):
                alpha[t, j] = np.sum(alpha[t-1] * self.transition_matrix_[:, j]) * \
                             self._emission_prob(returns[t], j)
            alpha[t] /= alpha[t].sum()
        
        log_likelihood = np.sum(np.log(np.sum(alpha, axis=1) + 1e-10))
        return alpha, log_likelihood
    
    def _backward(self, returns: np.ndarray) -> np.ndarray:
        """Backward algorithm"""
        T = len(returns)
        beta = np.zeros((T, self.n_states))
        beta[-1] = 1.0
        
        for t in range(T-2, -1, -1):
            for i in range(self.n_states):
                beta[t, i] = np.sum(
                    self.transition_matrix_[i, :] * 
                    self._emission_prob(returns[t+1], np.arange(self.n_states)) * 
                    beta[t+1]
                )
            beta[t] /= beta[t].sum()
        
        return beta
    
    def _emission_prob(self, x: float, state: int) -> float:
        """Gaussian emission probability"""
        mean = self.emission_means_[state]
        var = self.emission_vars_[state]
        return norm.pdf(x, mean, np.sqrt(var))
    
    def _compute_gamma(self, alpha: np.ndarray, beta: np.ndarray) -> np.ndarray:
        """Compute posterior state probabilities"""
        gamma = alpha * beta
        gamma /= gamma.sum(axis=1, keepdims=True)
        return gamma
    
    def _compute_xi(self, returns: np.ndarray, alpha: np.ndarray, beta: np.ndarray) -> np.ndarray:
        """Compute pairwise state transition probabilities"""
        T = len(returns)
        xi = np.zeros((T-1, self.n_states, self.n_states))
        
        for t in range(T-1):
            denom = 0
            for i in range(self.n_states):
                for j in range(self.n_states):
                    xi[t, i, j] = alpha[t, i] * self.transition_matrix_[i, j] * \
                                  self._emission_prob(returns[t+1], j) * beta[t+1, j]
                    denom += xi[t, i, j]
            if denom > 0:
                xi[t] /= denom
        
        return xi
    
    def _update_params(self, returns: np.ndarray, gamma: np.ndarray, xi: np.ndarray):
        """M-step: Update HMM parameters with Dirichlet prior for transition matrix"""
        T = len(returns)
        
        # Initial probabilities
        self.initial_probs_ = gamma[0]
        
        # Transition matrix with Dirichlet prior favoring self-transitions
        # Add pseudo-counts to maintain high self-transition probability
        alpha_prior = 1.0  # Base prior
        alpha_self = 100.0  # Strong prior for self-transitions
        
        trans_counts = xi.sum(axis=0)
        gamma_counts = gamma[:-1].sum(axis=0)
        
        # Add prior
        for i in range(self.n_states):
            for j in range(self.n_states):
                if i == j:
                    trans_counts[i, j] += alpha_self
                else:
                    trans_counts[i, j] += alpha_prior
            gamma_counts[i] += alpha_self + alpha_prior * (self.n_states - 1)
        
        self.transition_matrix_ = trans_counts / gamma_counts[:, np.newaxis]
        
        # Emission parameters
        for i in range(self.n_states):
            weight = gamma[:, i].sum()
            if weight > 1e-6:
                self.emission_means_[i] = np.sum(gamma[:, i] * returns) / weight
                self.emission_vars_[i] = np.sum(gamma[:, i] * (returns - self.emission_means_[i])**2) / weight
                self.emission_vars_[i] = max(self.emission_vars_[i], 1e-6)
    
    def predict_regimes(self, returns: np.ndarray) -> np.ndarray:
        """Predict most likely regime sequence (Viterbi algorithm)"""
        T = len(returns)
        delta = np.zeros((T, self.n_states))
        psi = np.zeros((T, self.n_states), dtype=int)
        
        # Initialization
        for i in range(self.n_states):
            delta[0, i] = np.log(self.initial_probs_[i] + 1e-10) + \
                          np.log(self._emission_prob(returns[0], i) + 1e-10)
        
        # Recursion
        for t in range(1, T):
            for j in range(self.n_states):
                trans_probs = delta[t-1] + np.log(self.transition_matrix_[:, j] + 1e-10)
                psi[t, j] = np.argmax(trans_probs)
                delta[t, j] = trans_probs[psi[t, j]] + np.log(self._emission_prob(returns[t], j) + 1e-10)
        
        # Backtrack
        states = np.zeros(T, dtype=int)
        states[-1] = np.argmax(delta[-1])
        for t in range(T-2, -1, -1):
            states[t] = psi[t+1, states[t+1]]
        
        return states
    
    def get_regime_sequence(self, returns: np.ndarray) -> List[RegimeState]:
        """Convert state sequence to RegimeState objects"""
        T = len(returns)
        states = self.predict_regimes(returns)
        
        # Map states to regime types based on emission means/variances
        regime_map = self._map_states_to_regimes()
        
        regime_sequence = []
        current_state = states[0]
        start_idx = 0
        
        for t in range(1, T):
            if states[t] != current_state:
                regime_sequence.append(RegimeState(
                    regime=regime_map[current_state],
                    confidence=0.8,  # Viterbi gives MAP estimate
                    start_idx=start_idx,
                    end_idx=t,
                    params={'mean': self.emission_means_[current_state], 
                           'var': self.emission_vars_[current_state]}
                ))
                current_state = states[t]
                start_idx = t
        
        # Close last regime
        regime_sequence.append(RegimeState(
            regime=regime_map[current_state],
            confidence=0.8,
            start_idx=start_idx,
            end_idx=T,
            params={'mean': self.emission_means_[current_state], 
                   'var': self.emission_vars_[current_state]}
        ))
        
        return regime_sequence
    
    def _map_states_to_regimes(self) -> Dict[int, RegimeType]:
        """Map HMM states to interpretable regime types"""
        regime_map = {}
        for i in range(self.n_states):
            mean = self.emission_means_[i]
            std = np.sqrt(self.emission_vars_[i])
            
            if std > 0.025:  # High volatility
                regime_map[i] = RegimeType.VOLATILE
            elif abs(mean) / std > 1.0:  # Clear trend
                regime_map[i] = RegimeType.TREND_UP if mean > 0 else RegimeType.TREND_DOWN
            else:  # Low vol, low drift -> mean reversion
                regime_map[i] = RegimeType.MEAN_REVERSION
        
        return regime_map


class RegimeDetector:
    """
    Unified regime detector combining multiple methods.
    """
    
    def __init__(self, method: Literal["volatility", "hmm", "ensemble"] = "ensemble"):
        if method not in ["volatility", "hmm", "ensemble"]:
            raise ValueError(f"Unknown method: {method}. Valid: 'volatility', 'hmm', 'ensemble'")
        self.method = method
        self.vol_detector = VolatilityRegimeDetector()
        self.hmm_detector = HMMRegimeDetector(n_states=3)
        self._fitted = False
    
    def fit(self, returns: pd.Series) -> 'RegimeDetector':
        """Fit the detector(s) to data"""
        if self.method in ["hmm", "ensemble"]:
            self.hmm_detector.fit(returns.values)
        self._fitted = True
        return self
    
    def detect(self, returns: pd.Series) -> List[RegimeState]:
        """Detect regimes using selected method"""
        if not self._fitted and self.method in ["hmm", "ensemble"]:
            self.fit(returns)
        
        if self.method == "volatility":
            return self.vol_detector.detect(returns)
        elif self.method == "hmm":
            return self.hmm_detector.get_regime_sequence(returns.values)
        elif self.method == "ensemble":
            vol_regimes = self.vol_detector.detect(returns)
            hmm_regimes = self.hmm_detector.get_regime_sequence(returns.values)
            return self._ensemble_regimes(vol_regimes, hmm_regimes)
        else:
            raise ValueError(f"Unknown method: {self.method}. Valid: 'volatility', 'hmm', 'ensemble'")
    
    def _ensemble_regimes(self, vol_regimes: List[RegimeState], hmm_regimes: List[RegimeState]) -> List[RegimeState]:
        """Combine volatility and HMM regime detections"""
        # Simple ensemble: use HMM for state sequence, volatility for confidence calibration
        return hmm_regimes  # For now, prefer HMM as it's more principled


def detect_regime(returns: pd.Series, method: str = "ensemble") -> List[RegimeState]:
    """
    Convenience function for regime detection.
    
    Args:
        returns: Return series (daily or intraday)
        method: "volatility", "hmm", or "ensemble"
    
    Returns:
        List of RegimeState objects
    """
    detector = RegimeDetector(method=method)
    return detector.detect(returns)


def get_current_regime(returns: pd.Series, method: str = "ensemble") -> RegimeState:
    """Get the current (most recent) regime"""
    regimes = detect_regime(returns, method)
    return regimes[-1] if regimes else RegimeState(RegimeType.UNKNOWN, 0.0, 0, None, {})


if __name__ == "__main__":
    # Quick test
    np.random.seed(42)
    n = 1000
    
    # Generate synthetic regime-switching returns
    regime1 = np.random.normal(0.001, 0.01, n//3)      # Trend up, low vol
    regime2 = np.random.normal(-0.001, 0.005, n//3)    # Trend down, very low vol
    regime3 = np.random.normal(0.0, 0.03, n//3)        # Volatile
    returns = pd.Series(np.concatenate([regime1, regime2, regime3]))
    
    detector = RegimeDetector(method="ensemble")
    regimes = detector.detect(returns)
    
    print("Detected regimes:")
    for r in regimes:
        print(f"  {r.regime.value}: idx {r.start_idx}-{r.end_idx}, conf={r.confidence:.2f}, params={r.params}")