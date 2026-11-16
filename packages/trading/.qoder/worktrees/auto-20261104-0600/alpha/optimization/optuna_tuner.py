"""
Optuna Hyperparameter Tuning for Alpha Models
Bayesian optimization with pruning, multi-objective support, and persistence
"""
import asyncio
import hashlib
import json
import logging
import os
import pickle
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import optuna
import optuna.visualization as vis
import pandas as pd
from optuna.pruners import HyperbandPruner, MedianPruner, NopPruner
from optuna.samplers import TPESampler, CmaEsSampler, RandomSampler
from optuna.storages import JournalFileStorage, JournalStorage, RDBStorage
from optuna.trial import Trial, TrialState

import sys
sys.path.insert(0, '/Users/aryanagarwal/alpha-system')

from alpha.models.linear import RidgeRegression as RidgeModel, LassoRegression as LassoModel, ElasticNet as ElasticNetModel
from alpha.models.tree import LightGBMModel, XGBoostModel
from alpha.validation.metrics import calculate_sharpe, calculate_sortino, calculate_ic

logger = logging.getLogger(__name__)


# ============================================================
# Data Classes
# ============================================================

@dataclass
class TuningConfig:
    """Configuration for hyperparameter tuning"""
    # Study settings
    study_name: str = "alpha_tuning"
    storage_url: str = "sqlite:///optuna_studies.db"  # or postgresql://...
    direction: str = "maximize"  # maximize IC, Sharpe, etc.
    
    # Sampler
    sampler: str = "tpe"  # tpe, cmaes, random
    sampler_kwargs: Dict = field(default_factory=dict)
    
    # Pruner
    pruner: str = "median"  # median, hyperband, none
    pruner_kwargs: Dict = field(default_factory=dict)
    
    # Optimization
    n_trials: int = 100
    timeout: Optional[int] = None  # seconds
    n_jobs: int = 1
    
    # Multi-objective
    multi_objective: bool = False
    objectives: List[str] = field(default_factory=lambda: ["ic", "sharpe"])
    weights: Optional[List[float]] = None
    
    # Callbacks
    callbacks: List[Callable] = field(default_factory=list)
    
    # Persistence
    save_top_k: int = 5
    checkpoint_interval: int = 10  # trials


@dataclass
class TrialResult:
    """Result of a single trial"""
    trial_id: int
    params: Dict[str, Any]
    values: List[float]  # objective values
    metrics: Dict[str, float]  # additional metrics
    duration: float
    state: TrialState
    datetime: str
    model_type: str
    fold_metrics: Optional[Dict] = None


@dataclass
class TuningResult:
    """Complete tuning results"""
    study_name: str
    best_params: Dict[str, Any]
    best_value: float
    best_trial: TrialResult
    all_trials: List[TrialResult]
    study: optuna.Study
    duration: float
    n_trials: int
    pruned_trials: int
    completed_trials: int


# ============================================================
# Base Model Interface for Tuning
# ============================================================

class TunableModel(ABC):
    """Abstract base class for tunable models"""
    
    @abstractmethod
    def get_search_space(self, trial: Trial) -> Dict[str, Any]:
        """Define hyperparameter search space for Optuna trial"""
        pass
    
    @abstractmethod
    def create_model(self, params: Dict[str, Any]) -> Any:
        """Create model instance with given parameters"""
        pass
    
    @abstractmethod
    def fit(self, X, y, **kwargs) -> Any:
        """Fit model"""
        pass
    
    @abstractmethod
    def predict(self, X) -> np.ndarray:
        """Predict"""
        pass
    
    @abstractmethod
    def score(self, X, y) -> float:
        """Score model (e.g., IC, Sharpe)"""
        pass


# ============================================================
# Model-Specific Search Spaces
# ============================================================

class RidgeTunable(TunableModel):
    def get_search_space(self, trial: Trial) -> Dict[str, Any]:
        return {
            'alpha': trial.suggest_float('alpha', 1e-4, 1e2, log=True),
            'solver': trial.suggest_categorical('solver', ['auto', 'svd', 'cholesky', 'lsqr', 'sparse_cg', 'sag', 'saga']),
        }
    
    def create_model(self, params: Dict[str, Any]) -> Any:
        from alpha.models.linear import RidgeModel
        return RidgeModel(**params)
    
    def fit(self, X, y, **kwargs):
        self.model = self.create_model(self.params)
        return self.model.fit(X, y, **kwargs)
    
    def predict(self, X):
        return self.model.predict(X)
    
    def score(self, X, y):
        from alpha.validation.metrics import calculate_ic
        pred = self.predict(X)
        return calculate_ic(pred, y)


class LassoTunable(TunableModel):
    def get_search_space(self, trial: Trial) -> Dict[str, Any]:
        return {
            'alpha': trial.suggest_float('alpha', 1e-4, 1e1, log=True),
            'max_iter': trial.suggest_int('max_iter', 1000, 5000),
            'selection': trial.suggest_categorical('selection', ['cyclic', 'random']),
        }
    
    def create_model(self, params: Dict[str, Any]) -> Any:
        from alpha.models.linear import LassoModel
        return LassoModel(**params)
    
    def fit(self, X, y, **kwargs):
        self.model = self.create_model(self.params)
        return self.model.fit(X, y, **kwargs)
    
    def predict(self, X):
        return self.model.predict(X)
    
    def score(self, X, y):
        from alpha.validation.metrics import calculate_ic
        pred = self.predict(X)
        return calculate_ic(pred, y)


class ElasticNetTunable(TunableModel):
    def get_search_space(self, trial: Trial) -> Dict[str, Any]:
        return {
            'alpha': trial.suggest_float('alpha', 1e-4, 1e1, log=True),
            'l1_ratio': trial.suggest_float('l1_ratio', 0.0, 1.0),
            'max_iter': trial.suggest_int('max_iter', 1000, 5000),
        }
    
    def create_model(self, params: Dict[str, Any]) -> Any:
        from alpha.models.linear import ElasticNetModel
        return ElasticNetModel(**params)
    
    def fit(self, X, y, **kwargs):
        self.model = self.create_model(self.params)
        return self.model.fit(X, y, **kwargs)
    
    def predict(self, X):
        return self.model.predict(X)
    
    def score(self, X, y):
        from alpha.validation.metrics import calculate_ic
        pred = self.predict(X)
        return calculate_ic(pred, y)


class LightGBMTunable(TunableModel):
    def get_search_space(self, trial: Trial) -> Dict[str, Any]:
        return {
            'n_estimators': trial.suggest_int('n_estimators', 50, 1000),
            'max_depth': trial.suggest_int('max_depth', 3, 12),
            'learning_rate': trial.suggest_float('learning_rate', 0.005, 0.3, log=True),
            'num_leaves': trial.suggest_int('num_leaves', 16, 256),
            'subsample': trial.suggest_float('subsample', 0.5, 1.0),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.5, 1.0),
            'reg_alpha': trial.suggest_float('reg_alpha', 1e-8, 10.0, log=True),
            'reg_lambda': trial.suggest_float('reg_lambda', 1e-8, 10.0, log=True),
            'min_child_samples': trial.suggest_int('min_child_samples', 5, 100),
            'min_child_weight': trial.suggest_float('min_child_weight', 1e-5, 10.0, log=True),
            'subsample_freq': trial.suggest_int('subsample_freq', 0, 10),
        }
    
    def create_model(self, params: Dict[str, Any]) -> Any:
        from alpha.models.tree import LightGBMModel
        return LightGBMModel(**params)
    
    def fit(self, X, y, **kwargs):
        self.model = self.create_model(self.params)
        return self.model.fit(X, y, **kwargs)
    
    def predict(self, X):
        return self.model.predict(X)
    
    def score(self, X, y):
        from alpha.validation.metrics import calculate_ic
        pred = self.predict(X)
        return calculate_ic(pred, y)


class XGBoostTunable(TunableModel):
    def get_search_space(self, trial: Trial) -> Dict[str, Any]:
        return {
            'n_estimators': trial.suggest_int('n_estimators', 50, 1000),
            'max_depth': trial.suggest_int('max_depth', 3, 10),
            'learning_rate': trial.suggest_float('learning_rate', 0.005, 0.3, log=True),
            'subsample': trial.suggest_float('subsample', 0.5, 1.0),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.5, 1.0),
            'reg_alpha': trial.suggest_float('reg_alpha', 1e-8, 10.0, log=True),
            'reg_lambda': trial.suggest_float('reg_lambda', 1e-8, 10.0, log=True),
            'gamma': trial.suggest_float('gamma', 1e-8, 10.0, log=True),
            'min_child_weight': trial.suggest_float('min_child_weight', 1e-3, 10.0, log=True),
        }
    
    def create_model(self, params: Dict[str, Any]) -> Any:
        from alpha.models.tree import XGBoostModel
        return XGBoostModel(**params)
    
    def fit(self, X, y, **kwargs):
        self.model = self.create_model(self.params)
        return self.model.fit(X, y, **kwargs)
    
    def predict(self, X):
        return self.model.predict(X)
    
    def score(self, X, y):
        from alpha.validation.metrics import calculate_ic
        pred = self.predict(X)
        return calculate_ic(pred, y)


# ============================================================
# Objective Functions
# ============================================================

class TuningObjective:
    """Objective function for Optuna optimization"""
    
    def __init__(
        self,
        model_class: type,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame,
        y_val: pd.Series,
        cv_splitter=None,
        metric: str = "ic",
        cv_folds: int = 5,
        sample_weight: Optional[pd.Series] = None,
    ):
        self.model_class = model_class
        self.X_train = X_train
        self.y_train = y_train
        self.X_val = X_val
        self.y_val = y_val
        self.cv_splitter = cv_splitter
        self.metric = metric
        self.cv_folds = cv_folds
        self.sample_weight = sample_weight
    
    def __call__(self, trial: Trial) -> Union[float, Tuple[float, ...]]:
        # Create tunable model
        if self.model_class == RidgeModel:
            tunable = RidgeTunable()
        elif self.model_class == LassoModel:
            tunable = LassoTunable()
        elif self.model_class == ElasticNetModel:
            tunable = ElasticNetTunable()
        elif self.model_class == LightGBMModel:
            tunable = LightGBMTunable()
        elif self.model_class == XGBoostModel:
            tunable = XGBoostTunable()
        else:
            raise ValueError(f"Unknown model class: {self.model_class}")
        
        # Get hyperparameters
        params = tunable.get_search_space(trial)
        
        # Cross-validation or single validation
        if self.cv_splitter:
            scores = []
            for fold, (train_idx, val_idx) in enumerate(self.cv_splitter.split(self.X_train)):
                X_tr = self.X_train.iloc[train_idx]
                y_tr = self.y_train.iloc[train_idx]
                X_val = self.X_train.iloc[val_idx]
                y_val = self.y_train.iloc[val_idx]
                
                model = self.model_class(**params)
                model.fit(X_tr, self.y_train.iloc[train_idx])
                pred = model.predict(X_val)
                
                from alpha.validation.metrics import calculate_ic
                score = calculate_ic(pred, y_val)
                scores.append(score)
            
            # Report intermediate value for pruning
            trial.report(np.mean(scores), step=fold)
            
            if trial.should_prune():
                raise optuna.TrialPruned()
            
            return np.mean(scores)
        else:
            # Single validation split
            model = self.model_class(**params)
            model.fit(self.X_train, self.y_train)
            pred = model.predict(self.X_val)
            
            from alpha.validation.metrics import calculate_ic, calculate_sharpe
            ic = calculate_ic(pred, self.y_val)
            sharpe = calculate_sharpe(pred, self.y_val)
            
            return (ic, sharpe) if self.metric == "multi" else ic


# ============================================================
# Hyperparameter Tuner
# ============================================================

class OptunaTuner:
    """
    Hyperparameter tuner using Optuna with support for:
    - Multiple samplers (TPE, CMA-ES, Random)
    - Multiple pruners (Median, Hyperband, Nop)
    - Multi-objective optimization
    - Study persistence (SQLite, PostgreSQL, Journal)
    - Distributed optimization
    - Callbacks and callbacks
    """
    
    def __init__(self, config: Optional[TuningConfig] = None):
        self.config = config or TuningConfig()
        self.study: Optional[optuna.Study] = None
        self._storage = None
        self._callbacks = []
        self._best_params = None
        self._best_value = -np.inf
        
    def _create_storage(self) -> Union[JournalStorage, RDBStorage]:
        """Create Optuna storage backend"""
        url = self.config.storage_url
        
        if url.startswith("sqlite:///"):
            return RDBStorage(url)
        elif url.startswith("postgresql://") or url.startswith("postgresql+psycopg2://"):
            return RDBStorage(url)
        elif url.startswith("journal://") or url.startswith("journal://"):
            path = url.replace("journal://", "")
            return JournalStorage(JournalFileStorage(path))
        else:
            # Default to SQLite
            return RDBStorage("sqlite:///optuna_studies.db")
    
    def _create_sampler(self) -> optuna.samplers.BaseSampler:
        sampler_type = self.config.sampler.lower()
        kwargs = self.config.sampler_kwargs
        
        if sampler_type == "tpe":
            return TPESampler(
                multivariate=kwargs.get('multivariate', True),
                group=kwargs.get('group', True),
                constant_liar=kwargs.get('constant_liar', True),
                seed=kwargs.get('seed', 42)
            )
        elif sampler_type == "cmaes":
            return CmaEsSampler(
                seed=kwargs.get('seed', 42),
                n_startup_trials=kwargs.get('n_startup_trials', 10),
                independent_sampler=kwargs.get('independent_sampler')
            )
        elif sampler_type == "random":
            return RandomSampler(seed=kwargs.get('seed', 42))
        else:
            return TPESampler(seed=42)
    
    def _create_pruner(self) -> optuna.pruners.BasePruner:
        pruner_type = self.config.pruner.lower()
        kwargs = self.config.pruner_kwargs
        
        if pruner_type == "median":
            return MedianPruner(
                n_startup_trials=kwargs.get('n_startup_trials', 5),
                n_warmup_steps=kwargs.get('n_warmup_steps', 10),
                interval_steps=kwargs.get('interval_steps', 1)
            )
        elif pruner_type == "hyperband":
            return HyperbandPruner(
                min_resource=kwargs.get('min_resource', 1),
                max_resource=kwargs.get('max_resource', 100),
                reduction_factor=kwargs.get('reduction_factor', 3)
            )
        elif pruner_type == "none":
            return NopPruner()
        else:
            return MedianPruner()
    
    def _create_study(self) -> optuna.Study:
        """Create or load Optuna study"""
        storage = self._create_storage()
        sampler = self._create_sampler()
        pruner = self._create_pruner()
        
        # Determine directions for multi-objective
        if self.config.multi_objective:
            directions = [optuna.study.StudyDirection.MAXIMIZE] * len(self.config.objectives)
        else:
            directions = [optuna.study.StudyDirection.MAXIMIZE if self.config.direction == "maximize" 
                         else optuna.study.StudyDirection.MINIMIZE]
        
        study = optuna.create_study(
            study_name=self.config.study_name,
            storage=storage,
            sampler=sampler,
            pruner=pruner,
            directions=directions,
            load_if_exists=True,
        )
        
        return study
    
    def _create_callbacks(self) -> List[Callable]:
        """Create Optuna callbacks"""
        callbacks = list(self.config.callbacks)
        
        # Add checkpoint callback
        def checkpoint_callback(study: optuna.Study, trial: optuna.Trial):
            if trial.number % self.config.checkpoint_interval == 0:
                self._save_checkpoint(study)
        
        callbacks.append(checkpoint_callback)
        
        # Add best trial tracker
        def best_tracker(study: optuna.Study, trial: optuna.Trial):
            if trial.state == optuna.trial.TrialState.COMPLETE:
                if self.config.multi_objective:
                    # For multi-objective, track Pareto front
                    pass
                else:
                    if self.config.direction == "maximize":
                        if trial.value > self._best_value:
                            self._best_value = trial.value
                            self._best_params = trial.params.copy()
                    else:
                        if trial.value < self._best_value:
                            self._best_value = trial.value
                            self._best_params = trial.params.copy()
        
        callbacks.append(best_tracker)
        
        return callbacks
    
    def _save_checkpoint(self, study: optuna.Study):
        """Save study checkpoint"""
        try:
            # Save best params
            checkpoint = {
                'study_name': self.config.study_name,
                'best_params': study.best_params,
                'best_value': study.best_value,
                'n_trials': len(study.trials),
                'timestamp': datetime.now().isoformat(),
            }
            Path("optuna_checkpoints").mkdir(exist_ok=True)
            checkpoint_path = f"optuna_checkpoints/{self.config.study_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(checkpoint_path, 'w') as f:
                json.dump(checkpoint, f, indent=2)
        except Exception as e:
            logger.warning(f"Checkpoint save failed: {e}")
    
    def optimize(
        self,
        objective: Callable,
        n_trials: Optional[int] = None,
        timeout: Optional[int] = None,
        n_jobs: Optional[int] = None,
        callbacks: Optional[List[Callable]] = None,
        gc_after_trial: bool = True,
        show_progress_bar: bool = True,
    ) -> TuningResult:
        """
        Run hyperparameter optimization
        
        Args:
            objective: Objective function to optimize
            n_trials: Number of trials (overrides config)
            timeout: Timeout in seconds (overrides config)
            n_jobs: Number of parallel jobs (overrides config)
            callbacks: Additional callbacks
            gc_after_trial: Garbage collect after each trial
            show_progress_bar: Show progress bar
            
        Returns:
            TuningResult with best params and trial history
        """
        n_trials = n_trials or self.config.n_trials
        timeout = timeout or self.config.timeout
        n_jobs = n_jobs or self.config.n_jobs
        callbacks = (callbacks or []) + self._create_callbacks()
        
        logger.info(f"Starting optimization: {self.config.study_name}")
        logger.info(f"Trials: {n_trials}, Timeout: {timeout}s, Jobs: {n_jobs}")
        
        start_time = time.time()
        
        # Create or load study
        self.study = self._create_study()
        
        # Add pruning callback if using sklearn
        pruning_callbacks = []
        # Note: Would add SklearnPruningCallback if using sklearn models
        
        # Run optimization
        self.study.optimize(
            objective,
            n_trials=n_trials,
            timeout=timeout,
            n_jobs=n_jobs,
            callbacks=callbacks,
            gc_after_trial=gc_after_trial,
            show_progress_bar=show_progress_bar,
            catch=(Exception,),
        )
        
        duration = time.time() - start_time
        
        # Compile results
        result = self._compile_results(duration)
        
        logger.info(f"Optimization complete: {result.n_trials} trials, "
                   f"Best value: {result.best_value:.6f}, "
                   f"Duration: {duration:.1f}s")
        
        return result
    
    def _compile_results(self, duration: float) -> TuningResult:
        """Compile tuning results"""
        study = self.study
        
        # Get all trials
        trials = study.trials
        completed = [t for t in trials if t.state == TrialState.COMPLETE]
        pruned = [t for t in trials if t.state == TrialState.PRUNED]
        failed = [t for t in trials if t.state == TrialState.FAIL]
        
        # Convert to TrialResult objects
        all_trials = []
        for t in trials:
            if t.state == TrialState.COMPLETE:
                values = t.values if isinstance(t.values, list) else [t.value]
                all_trials.append(TrialResult(
                    trial_id=t.number,
                    params=t.params,
                    values=values,
                    metrics=t.user_attrs,
                    duration=t.datetime_complete.timestamp() - t.datetime_start.timestamp() if t.datetime_complete and t.datetime_start else 0,
                    state=t.state,
                    datetime=t.datetime_start.isoformat() if t.datetime_start else "",
                    model_type="",
                ))
        
        best_trial = study.best_trial
        best_trial_result = TrialResult(
            trial_id=best_trial.number,
            params=best_trial.params,
            values=best_trial.values if isinstance(best_trial.values, list) else [best_trial.value],
            metrics=best_trial.user_attrs,
            duration=best_trial.datetime_complete.timestamp() - best_trial.datetime_start.timestamp() if best_trial.datetime_complete and best_trial.datetime_start else 0,
            state=best_trial.state,
            datetime=best_trial.datetime_start.isoformat() if best_trial.datetime_start else "",
            model_type="",
        )
        
        return TuningResult(
            study_name=self.config.study_name,
            best_params=study.best_params,
            best_value=study.best_value,
            best_trial=best_trial_result,
            all_trials=all_trials,
            study=study,
            duration=duration,
            n_trials=len(trials),
            pruned_trials=len(pruned),
            completed_trials=len(completed),
        )
    
    def get_best_params(self) -> Dict[str, Any]:
        """Get best parameters found"""
        if self.study:
            return self.study.best_params
        return self._best_params or {}
    
    def get_best_value(self) -> float:
        """Get best objective value"""
        if self.study:
            return self.study.best_value
        return self._best_value
    
    def get_pareto_front(self) -> List[Dict]:
        """Get Pareto front for multi-objective optimization"""
        if not self.study or not self.config.multi_objective:
            return []
        
        pareto_trials = []
        for trial in self.study.best_trials:
            pareto_trials.append({
                'params': trial.params,
                'values': trial.values,
                'trial_number': trial.number,
            })
        return pareto_trials
    
    def get_param_importance(self) -> Dict[str, float]:
        """Get parameter importance using Optuna's built-in importance"""
        if not self.study:
            return {}
        try:
            return optuna.importance.get_param_importances(self.study)
        except:
            return {}
    
    def get_contour_data(self, param1: str, param2: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Get contour plot data for two parameters"""
        if not self.study:
            return None, None, None
        try:
            fig = vis.plot_contour(self.study, params=[param1, param2])
            # Extract data from plotly figure
            return fig.data[0].x, fig.data[0].y, fig.data[0].z
        except:
            return None, None, None
    
    def plot_optimization_history(self) -> Any:
        """Plot optimization history"""
        if not self.study:
            return None
        return vis.plot_optimization_history(self.study)
    
    def plot_param_importances(self) -> Any:
        """Plot parameter importances"""
        if not self.study:
            return None
        return vis.plot_param_importances(self.study)
    
    def plot_parallel_coordinate(self, params: List[str] = None) -> Any:
        """Plot parallel coordinate plot"""
        if not self.study:
            return None
        return vis.plot_parallel_coordinate(self.study, params=params)
    
    def plot_slice(self, param: str = None) -> Any:
        """Plot slice plot"""
        if not self.study:
            return None
        return vis.plot_slice(self.study, param=param)
    
    def plot_edf(self) -> Any:
        """Plot empirical distribution function"""
        if not self.study:
            return None
        return vis.plot_edf(self.study)
    
    def save_study(self, path: str):
        """Save study to file"""
        if not self.study:
            return
        
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'wb') as f:
            pickle.dump(self.study, f)
        logger.info(f"Study saved to {path}")
    
    def load_study(self, path: str) -> optuna.Study:
        """Load study from file"""
        with open(path, 'rb') as f:
            self.study = pickle.load(f)
        logger.info(f"Study loaded from {path}")
        return self.study
    
    def resume_study(self, study_name: str, storage_url: str = None) -> optuna.Study:
        """Resume existing study"""
        storage = self._create_storage() if storage_url is None else storage_url
        self.study = optuna.load_study(study_name=study_name, storage=storage)
        return self.study


# ============================================================
# High-Level Tuning Functions
# ============================================================

async def tune_model(
    model_name: str,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    config: Optional[TuningConfig] = None,
    cv_splitter=None,
    metric: str = "ic",
) -> TuningResult:
    """
    High-level function to tune a single model
    
    Args:
        model_name: Name of model to tune
        X_train, y_train: Training data
        X_val, y_val: Validation data
        config: Tuning configuration
        cv_splitter: Cross-validation splitter
        metric: Metric to optimize ('ic', 'sharpe', 'multi')
        
    Returns:
        TuningResult with best parameters
    """
    # Map model names to classes
    model_map = {
        'ridge': RidgeModel,
        'lasso': LassoModel,
        'elasticnet': ElasticNetModel,
        'lightgbm': LightGBMModel,
        'xgboost': XGBoostModel,
    }
    
    model_class = model_map.get(model_name.lower())
    if not model_class:
        raise ValueError(f"Unknown model: {model_name}")
    
    config = config or TuningConfig(study_name=f"{model_name}_tuning")
    
    # Create objective
    objective = TuningObjective(
        model_class=model_class,
        X_train=X_train,
        y_train=y_train,
        X_val=X_val,
        y_val=y_val,
        cv_splitter=cv_splitter,
        metric=metric,
    )
    
    # Create tuner and run
    tuner = OptunaTuner(config)
    result = tuner.optimize(objective)
    
    logger.info(f"Tuning complete for {model_name}: best {objective.metric} = {result.best_value:.6f}")
    
    return result


async def tune_ensemble(
    model_configs: List[Dict],
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    config: Optional[TuningConfig] = None,
) -> Dict[str, TuningResult]:
    """
    Tune multiple models in parallel
    
    Args:
        model_configs: List of dicts with 'model_name' and optional 'config'
        X_train, y_train: Training data
        X_val, y_val: Validation data
        config: Base tuning config (merged with model-specific configs)
        
    Returns:
        Dict of model_name -> TuningResult
    """
    tasks = []
    
    for model_config in model_configs:
        model_name = model_config['model_name']
        model_config_obj = config or TuningConfig()
        
        # Merge configs
        if 'config' in model_config:
            # Merge custom config
            pass
        
        task = tune_model(
            model_name=model_name,
            X_train=X_train,
            y_train=y_train,
            X_val=X_val,
            y_val=y_val,
            config=model_config_obj,
        )
        tasks.append(task)
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    results_dict = {}
    for i, (model_config, result) in enumerate(zip(model_configs, results)):
        if isinstance(result, Exception):
            logger.error(f"Tuning failed for {model_config['model_name']}: {result}")
        else:
            results_dict[model_config['model_name']] = result
    
    return results_dict


def create_ensemble_tuner(
    base_models: Dict[str, Any],
    meta_learner: str = "ridge",
    cv_splitter=None,
) -> OptunaTuner:
    """
    Create tuner for ensemble stacking
    """
    # This would tune meta-learner hyperparameters
    # while keeping base models fixed or also tuning them
    pass


# ============================================================
# Visualization Helpers
# ============================================================

def plot_tuning_results(result: TuningResult, save_dir: str = None):
    """Generate and optionally save visualization plots"""
    import matplotlib.pyplot as plt
    import seaborn as sns
    
    if not result.all_trials:
        return
    
    trials = result.all_trials
    df = pd.DataFrame([
        {**t.params, 'value': t.values[0] if t.values else 0, 'trial': t.trial_id}
        for t in trials
    ])
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    # 1. Optimization history
    ax = axes[0, 0]
    values = [t.values[0] if t.values else 0 for t in result.all_trials]
    ax.plot(range(len(values)), values, 'o-', alpha=0.6)
    ax.set_xlabel('Trial')
    ax.set_ylabel('Objective Value')
    ax.set_title('Optimization History')
    ax.grid(True, alpha=0.3)
    
    # 2. Parameter importance (if available)
    ax = axes[0, 1]
    # Would plot param importance if available
    
    # 3. Parallel coordinates
    ax = axes[1, 0]
    # Parallel coordinate plot for top parameters
    
    # 4. Best params
    ax = axes[1, 1]
    ax.axis('off')
    best_text = "Best Params:\n" + "\n".join(
        f"  {k}: {v:.6f}" if isinstance(v, float) else f"  {k}: {v}"
        for k, v in result.best_params.items()
    )
    ax.text(0.1, 0.9, best_text, transform=ax.transAxes, fontsize=10, family='monospace')
    ax.set_title('Best Parameters')
    
    plt.tight_layout()
    
    if save_dir:
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        plt.savefig(Path(save_dir) / "tuning_results.png", dpi=150, bbox_inches='tight')
        plt.close()
    
    return fig


# ============================================================
# Integration with Existing System
# ============================================================

def integrate_with_alpha_system(tuner: OptunaTuner, study_name: str = None) -> OptunaTuner:
    """Integrate tuner with existing alpha system"""
    # This would connect to the alpha system's data pipeline
    pass


# ============================================================
# Example Usage
# ============================================================

async def example_usage():
    """Example of how to use the tuner"""
    
    # Sample data
    np.random.seed(42)
    n_samples = 1000
    n_features = 20
    
    X = pd.DataFrame(np.random.randn(n_samples, n_features))
    y = pd.Series(np.random.randn(n_samples))
    
    # Split
    split = int(0.8 * len(X))
    X_train, X_val = X.iloc[:split], X.iloc[split:]
    y_train, y_val = y.iloc[:split], y.iloc[split:]
    
    # Configure tuning
    config = TuningConfig(
        study_name="lightgbm_tuning",
        storage_url="sqlite:///tuning.db",
        n_trials=50,
        direction="maximize",
        sampler="tpe",
        pruner="hyperband",
        multi_objective=False,
    )
    
    # Run tuning
    result = await tune_model(
        model_name="lightgbm",
        X_train=X_train,
        y_train=y_train,
        X_val=X_val,
        y_val=y_val,
        config=TuningConfig(
            study_name="lgbm_tuning",
            n_trials=30,
            storage_url="sqlite:///tuning.db",
        ),
    )
    
    print(f"Best params: {result.best_params}")
    print(f"Best IC: {result.best_value:.6f}")
    
    # Plot results
    plot_tuning_results(result, save_dir="tuning_results")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(example_usage())
