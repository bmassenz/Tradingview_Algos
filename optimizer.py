"""
Strategy Optimizer - Grid Search, Bayesian Optimization, and Walk-Forward Analysis
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Callable, Optional
from dataclasses import dataclass
import itertools
from concurrent.futures import ProcessPoolExecutor
import warnings
warnings.filterwarnings('ignore')


@dataclass
class OptimizationResult:
    best_params: dict
    best_score: float
    all_results: pd.DataFrame
    sensitivity_data: dict
    walk_forward_results: dict


class GridSearchOptimizer:
    """Step 1: Exhaustive grid search on core parameters."""

    def __init__(self, objective_fn: Callable, param_grid: dict):
        """
        objective_fn: function(params_dict) -> dict with 'sharpe', 'max_dd', 'cagr', etc.
        param_grid: dict of param_name -> list of values to test
        """
        self.objective_fn = objective_fn
        self.param_grid = param_grid

    def run(self, maximize: str = 'sharpe', constraint: dict = None) -> pd.DataFrame:
        """
        Run grid search over all parameter combinations.
        constraint: e.g., {'max_dd': ('<=', 0.20)} to filter results
        Returns DataFrame sorted by objective, columns = params + metrics
        """
        param_names = list(self.param_grid.keys())
        param_values = list(self.param_grid.values())
        all_combos = list(itertools.product(*param_values))

        records = []
        for combo in all_combos:
            params = dict(zip(param_names, combo))
            try:
                metrics = self.objective_fn(params)
            except Exception:
                continue

            row = {}
            row.update(params)
            row.update(metrics)
            records.append(row)

        if not records:
            return pd.DataFrame()

        results_df = pd.DataFrame(records)

        # Apply constraints to filter
        if constraint:
            for metric_name, (op, threshold) in constraint.items():
                if metric_name not in results_df.columns:
                    continue
                if op == '<=':
                    results_df = results_df[results_df[metric_name] <= threshold]
                elif op == '>=':
                    results_df = results_df[results_df[metric_name] >= threshold]
                elif op == '<':
                    results_df = results_df[results_df[metric_name] < threshold]
                elif op == '>':
                    results_df = results_df[results_df[metric_name] > threshold]
                elif op == '==':
                    results_df = results_df[results_df[metric_name] == threshold]

        if maximize in results_df.columns:
            results_df = results_df.sort_values(by=maximize, ascending=False).reset_index(drop=True)

        return results_df


class BayesianOptimizer:
    """Step 2: Bayesian optimization to refine top parameters."""

    def __init__(self, objective_fn: Callable, param_space: dict, n_initial: int = 10):
        """
        param_space: dict of param_name -> (min_val, max_val) tuples
        """
        self.objective_fn = objective_fn
        self.param_space = param_space
        self.n_initial = n_initial

    def _random_sample(self, rng: np.random.RandomState) -> dict:
        """Generate a single random parameter set within bounds."""
        params = {}
        for name, (lo, hi) in self.param_space.items():
            params[name] = lo + rng.random() * (hi - lo)
        return params

    def _expected_improvement(self, candidate_score_estimate: float,
                              best_score: float, uncertainty: float) -> float:
        """Compute expected improvement given a predicted mean and uncertainty."""
        if uncertainty <= 0:
            return 0.0
        z = (candidate_score_estimate - best_score) / uncertainty
        # Approximate the EI using the normal CDF/PDF
        # EI = (mu - best) * Phi(z) + sigma * phi(z)
        phi = np.exp(-0.5 * z * z) / np.sqrt(2.0 * np.pi)
        big_phi = 0.5 * (1.0 + _erf_approx(z / np.sqrt(2.0)))
        ei = (candidate_score_estimate - best_score) * big_phi + uncertainty * phi
        return max(ei, 0.0)

    def _build_surrogate(self, X: np.ndarray, y: np.ndarray,
                         candidates: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Simple surrogate using inverse-distance-weighted interpolation.
        Returns (predicted_means, predicted_uncertainties) for each candidate.
        """
        n_candidates = candidates.shape[0]
        means = np.zeros(n_candidates)
        uncertainties = np.zeros(n_candidates)

        for i in range(n_candidates):
            dists = np.sqrt(np.sum((X - candidates[i]) ** 2, axis=1))
            dists = np.maximum(dists, 1e-10)

            # Inverse distance weights
            weights = 1.0 / dists
            weights /= weights.sum()

            means[i] = np.dot(weights, y)

            # Uncertainty: weighted variance + bonus for being far from observed points
            min_dist = dists.min()
            variance = np.dot(weights, (y - means[i]) ** 2)
            # Scale uncertainty by minimum distance to encourage exploration
            dist_scale = min_dist / (np.median(dists) + 1e-10)
            uncertainties[i] = np.sqrt(variance) + dist_scale * np.std(y)

        return means, uncertainties

    def optimize(self, n_iterations: int = 50, maximize: str = 'sharpe',
                 constraint: dict = None) -> OptimizationResult:
        """
        Run Bayesian optimization.
        1. Generate n_initial random parameter sets within bounds
        2. Evaluate each
        3. For remaining iterations, use surrogate + expected improvement
        4. Return best result meeting constraints
        """
        rng = np.random.RandomState(42)
        param_names = list(self.param_space.keys())
        bounds_lo = np.array([self.param_space[n][0] for n in param_names])
        bounds_hi = np.array([self.param_space[n][1] for n in param_names])
        n_params = len(param_names)

        evaluated_params_list = []
        evaluated_X = []
        evaluated_scores = []
        all_records = []

        def _evaluate(params: dict) -> Tuple[float, dict]:
            metrics = self.objective_fn(params)
            score = metrics.get(maximize, 0.0)

            # Check constraints - penalize violations
            if constraint:
                for metric_name, (op, threshold) in constraint.items():
                    val = metrics.get(metric_name, None)
                    if val is None:
                        continue
                    violated = False
                    if op == '<=' and val > threshold:
                        violated = True
                    elif op == '>=' and val < threshold:
                        violated = True
                    elif op == '<' and val >= threshold:
                        violated = True
                    elif op == '>' and val <= threshold:
                        violated = True
                    if violated:
                        score = -1e6
            return score, metrics

        # Phase 1: random initial samples
        for _ in range(min(self.n_initial, n_iterations)):
            params = self._random_sample(rng)
            try:
                score, metrics = _evaluate(params)
            except Exception:
                continue

            x_vec = np.array([params[n] for n in param_names])
            evaluated_params_list.append(params.copy())
            evaluated_X.append(x_vec)
            evaluated_scores.append(score)

            row = {}
            row.update(params)
            row.update(metrics)
            row['_score'] = score
            all_records.append(row)

        # Phase 2: surrogate-guided search
        remaining = n_iterations - self.n_initial
        n_candidates_per_iter = 200

        for _ in range(max(remaining, 0)):
            if len(evaluated_X) < 2:
                # Not enough data for surrogate, sample randomly
                params = self._random_sample(rng)
            else:
                X_arr = np.array(evaluated_X)
                y_arr = np.array(evaluated_scores)
                best_so_far = y_arr.max()

                # Normalize X to [0, 1] for distance calculations
                spread = bounds_hi - bounds_lo
                spread[spread == 0] = 1.0
                X_norm = (X_arr - bounds_lo) / spread

                # Generate random candidates
                candidates_raw = rng.random((n_candidates_per_iter, n_params))
                candidates = bounds_lo + candidates_raw * (bounds_hi - bounds_lo)
                candidates_norm = (candidates - bounds_lo) / spread

                means, uncertainties = self._build_surrogate(X_norm, y_arr, candidates_norm)

                # Compute EI for each candidate
                ei_values = np.array([
                    self._expected_improvement(means[j], best_so_far, uncertainties[j])
                    for j in range(n_candidates_per_iter)
                ])

                best_candidate_idx = np.argmax(ei_values)
                best_candidate = candidates[best_candidate_idx]
                params = dict(zip(param_names, best_candidate.tolist()))

            try:
                score, metrics = _evaluate(params)
            except Exception:
                continue

            x_vec = np.array([params[n] for n in param_names])
            evaluated_params_list.append(params.copy())
            evaluated_X.append(x_vec)
            evaluated_scores.append(score)

            row = {}
            row.update(params)
            row.update(metrics)
            row['_score'] = score
            all_records.append(row)

        # Build results
        all_results_df = pd.DataFrame(all_records)
        if '_score' in all_results_df.columns:
            all_results_df = all_results_df.sort_values('_score', ascending=False).reset_index(drop=True)

        # Find best valid result
        valid_mask = all_results_df['_score'] > -1e5 if '_score' in all_results_df.columns else pd.Series([True] * len(all_results_df))
        valid_results = all_results_df[valid_mask]

        if len(valid_results) > 0:
            best_row = valid_results.iloc[0]
            best_params = {n: best_row[n] for n in param_names}
            best_score = best_row['_score']
        else:
            best_params = evaluated_params_list[0] if evaluated_params_list else {}
            best_score = evaluated_scores[0] if evaluated_scores else 0.0

        return OptimizationResult(
            best_params=best_params,
            best_score=best_score,
            all_results=all_results_df,
            sensitivity_data={},
            walk_forward_results={}
        )


class WalkForwardOptimizer:
    """Step 3: Rolling walk-forward optimization."""

    def __init__(self, data: pd.DataFrame, strategy_fn: Callable,
                 is_window: int = 252, oos_window: int = 63):
        """
        data: Full OHLCV DataFrame
        strategy_fn: function(data, params) -> backtest_results dict with metrics
        is_window: In-sample window in trading days (252 = ~1 year)
        oos_window: Out-of-sample window (63 = ~3 months)
        """
        self.data = data
        self.strategy_fn = strategy_fn
        self.is_window = is_window
        self.oos_window = oos_window

    def _mini_grid_search(self, is_data: pd.DataFrame, param_grid: dict,
                          maximize: str = 'sharpe') -> Tuple[dict, float]:
        """Run a grid search on the in-sample data slice and return best params + score."""
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        all_combos = list(itertools.product(*param_values))

        best_params = None
        best_score = -np.inf

        for combo in all_combos:
            params = dict(zip(param_names, combo))
            try:
                metrics = self.strategy_fn(is_data, params)
                score = metrics.get(maximize, -np.inf)
                if score > best_score:
                    best_score = score
                    best_params = params.copy()
            except Exception:
                continue

        if best_params is None:
            # Fallback: use first combination
            best_params = dict(zip(param_names, all_combos[0]))
            best_score = 0.0

        return best_params, best_score

    def run(self, param_grid: dict, maximize: str = 'sharpe') -> dict:
        """
        Rolling walk-forward:
        1. For each window: optimize on IS, test on OOS
        2. Track OOS performance for each window
        3. Calculate % of profitable OOS windows
        4. Calculate overall OOS equity curve by chaining windows

        Returns dict with:
        - windows: list of window result dicts
        - pct_profitable_oos: float
        - combined_oos_equity: pd.Series
        - combined_oos_sharpe: float
        """
        n_rows = len(self.data)
        total_window = self.is_window + self.oos_window

        if n_rows < total_window:
            return {
                'windows': [],
                'pct_profitable_oos': 0.0,
                'combined_oos_equity': pd.Series(dtype=float),
                'combined_oos_sharpe': 0.0,
            }

        windows = []
        oos_returns_all = []

        start = 0
        while start + total_window <= n_rows:
            is_start = start
            is_end = start + self.is_window
            oos_start = is_end
            oos_end = min(is_end + self.oos_window, n_rows)

            is_data = self.data.iloc[is_start:is_end].copy()
            oos_data = self.data.iloc[oos_start:oos_end].copy()

            # Optimize on IS
            best_params, is_score = self._mini_grid_search(is_data, param_grid, maximize)

            # Evaluate on OOS
            try:
                oos_metrics = self.strategy_fn(oos_data, best_params)
                oos_sharpe = oos_metrics.get('sharpe', 0.0)
                oos_return = oos_metrics.get('total_return', 0.0)
                oos_equity = oos_metrics.get('equity_curve', None)
            except Exception:
                oos_sharpe = 0.0
                oos_return = 0.0
                oos_equity = None

            # Determine date labels if index is datetime, otherwise use integer positions
            if hasattr(self.data.index, 'strftime'):
                is_start_label = self.data.index[is_start]
                is_end_label = self.data.index[is_end - 1]
                oos_start_label = self.data.index[oos_start]
                oos_end_label = self.data.index[oos_end - 1]
            else:
                is_start_label = is_start
                is_end_label = is_end - 1
                oos_start_label = oos_start
                oos_end_label = oos_end - 1

            window_result = {
                'is_start': is_start_label,
                'is_end': is_end_label,
                'oos_start': oos_start_label,
                'oos_end': oos_end_label,
                'is_sharpe': is_score,
                'oos_sharpe': oos_sharpe,
                'oos_return': oos_return,
                'best_params': best_params,
            }
            windows.append(window_result)

            # Collect OOS equity data for chaining
            if oos_equity is not None and isinstance(oos_equity, (pd.Series, np.ndarray)):
                oos_returns_all.append(pd.Series(oos_equity))
            else:
                # Synthesize a simple equity line from oos_return spread over the window
                n_oos = oos_end - oos_start
                if n_oos > 0:
                    daily_ret = (1.0 + oos_return) ** (1.0 / n_oos) - 1.0
                    equity_line = (1.0 + daily_ret) ** np.arange(1, n_oos + 1)
                    oos_returns_all.append(pd.Series(equity_line))

            # Advance by oos_window to create rolling (non-overlapping OOS) windows
            start += self.oos_window

        # Calculate combined OOS metrics
        n_profitable = sum(1 for w in windows if w['oos_return'] > 0)
        pct_profitable = n_profitable / len(windows) if windows else 0.0

        # Chain OOS equity curves
        if oos_returns_all:
            combined_pieces = []
            cumulative_factor = 1.0
            for eq_series in oos_returns_all:
                # Normalize each piece so it starts at 1, then scale by cumulative factor
                eq_arr = np.array(eq_series)
                if len(eq_arr) == 0:
                    continue
                normalized = eq_arr / eq_arr[0] if eq_arr[0] != 0 else eq_arr
                scaled = normalized * cumulative_factor
                combined_pieces.append(scaled)
                cumulative_factor = scaled[-1]

            combined_equity = pd.Series(np.concatenate(combined_pieces))
        else:
            combined_equity = pd.Series(dtype=float)

        # Calculate combined OOS Sharpe from the chained equity curve
        if len(combined_equity) > 1:
            daily_returns = combined_equity.pct_change().dropna()
            if daily_returns.std() > 0:
                combined_sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
            else:
                combined_sharpe = 0.0
        else:
            combined_sharpe = 0.0

        return {
            'windows': windows,
            'pct_profitable_oos': pct_profitable,
            'combined_oos_equity': combined_equity,
            'combined_oos_sharpe': combined_sharpe,
        }


class RobustnessAnalyzer:
    """Step 4: Parameter sensitivity and robustness testing."""

    def __init__(self, objective_fn: Callable, optimal_params: dict):
        self.objective_fn = objective_fn
        self.optimal_params = optimal_params

    def parameter_sensitivity(self, perturbation: float = 0.20) -> dict:
        """
        Test +/- perturbation on each parameter.
        Returns dict of param_name -> sensitivity info.
        """
        # Get baseline performance
        try:
            base_metrics = self.objective_fn(self.optimal_params)
            base_sharpe = base_metrics.get('sharpe', 0.0)
        except Exception:
            base_sharpe = 0.0

        results = {}

        for param_name, base_value in self.optimal_params.items():
            if not isinstance(base_value, (int, float)):
                continue

            # Perturb down
            params_minus = self.optimal_params.copy()
            perturbed_minus = base_value * (1.0 - perturbation)
            if isinstance(base_value, int):
                perturbed_minus = int(round(perturbed_minus))
            params_minus[param_name] = perturbed_minus

            try:
                metrics_minus = self.objective_fn(params_minus)
                sharpe_minus = metrics_minus.get('sharpe', 0.0)
            except Exception:
                sharpe_minus = 0.0

            # Perturb up
            params_plus = self.optimal_params.copy()
            perturbed_plus = base_value * (1.0 + perturbation)
            if isinstance(base_value, int):
                perturbed_plus = int(round(perturbed_plus))
            params_plus[param_name] = perturbed_plus

            try:
                metrics_plus = self.objective_fn(params_plus)
                sharpe_plus = metrics_plus.get('sharpe', 0.0)
            except Exception:
                sharpe_plus = 0.0

            # Calculate degradation
            if base_sharpe != 0:
                degradation_minus = abs(sharpe_minus - base_sharpe) / abs(base_sharpe)
                degradation_plus = abs(sharpe_plus - base_sharpe) / abs(base_sharpe)
            else:
                degradation_minus = abs(sharpe_minus - base_sharpe)
                degradation_plus = abs(sharpe_plus - base_sharpe)

            max_degradation = max(degradation_minus, degradation_plus)

            results[param_name] = {
                'base_sharpe': base_sharpe,
                'minus_20_sharpe': sharpe_minus,
                'plus_20_sharpe': sharpe_plus,
                'max_degradation_pct': max_degradation,
                'is_robust': max_degradation < 0.35,
            }

        return results

    def regime_analysis(self, data: pd.DataFrame, signals: pd.DataFrame) -> dict:
        """
        Break down performance by market regime:
        - Bull (>20% annualized return over 6mo rolling)
        - Bear (<-20% annualized)
        - Sideways (in between)
        Returns metrics for each regime.
        """
        # Determine the price column
        if 'close' in data.columns:
            prices = data['close']
        elif 'Close' in data.columns:
            prices = data['Close']
        else:
            # Fallback: use the first numeric column
            numeric_cols = data.select_dtypes(include=[np.number]).columns
            prices = data[numeric_cols[0]] if len(numeric_cols) > 0 else pd.Series(dtype=float)

        if len(prices) < 126:
            return {'bull': {}, 'bear': {}, 'sideways': {}}

        # Calculate 6-month (~126 trading days) rolling annualized return
        rolling_return = prices.pct_change(126).dropna()
        annualized_return = ((1 + rolling_return) ** (252 / 126)) - 1

        # Classify each day into a regime
        regime = pd.Series('sideways', index=annualized_return.index)
        regime[annualized_return > 0.20] = 'bull'
        regime[annualized_return < -0.20] = 'bear'

        # Align signals with regime
        # Expect signals to have a 'returns' or 'strategy_returns' column
        if 'strategy_returns' in signals.columns:
            strat_returns = signals['strategy_returns']
        elif 'returns' in signals.columns:
            strat_returns = signals['returns']
        else:
            numeric_cols = signals.select_dtypes(include=[np.number]).columns
            strat_returns = signals[numeric_cols[0]] if len(numeric_cols) > 0 else pd.Series(dtype=float)

        # Align indices
        common_idx = regime.index.intersection(strat_returns.index)
        regime_aligned = regime.loc[common_idx]
        returns_aligned = strat_returns.loc[common_idx]

        results = {}
        for regime_name in ['bull', 'bear', 'sideways']:
            mask = regime_aligned == regime_name
            regime_returns = returns_aligned[mask]

            if len(regime_returns) < 2:
                results[regime_name] = {
                    'n_days': int(mask.sum()),
                    'total_return': 0.0,
                    'annualized_return': 0.0,
                    'sharpe': 0.0,
                    'max_drawdown': 0.0,
                    'win_rate': 0.0,
                }
                continue

            total_ret = (1 + regime_returns).prod() - 1
            n_days = len(regime_returns)
            ann_ret = (1 + total_ret) ** (252 / max(n_days, 1)) - 1

            mean_ret = regime_returns.mean()
            std_ret = regime_returns.std()
            sharpe = (mean_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0.0

            # Max drawdown within this regime
            cum = (1 + regime_returns).cumprod()
            running_max = cum.cummax()
            drawdown = (cum - running_max) / running_max
            max_dd = drawdown.min() if len(drawdown) > 0 else 0.0

            win_rate = (regime_returns > 0).mean()

            results[regime_name] = {
                'n_days': n_days,
                'total_return': float(total_ret),
                'annualized_return': float(ann_ret),
                'sharpe': float(sharpe),
                'max_drawdown': float(max_dd),
                'win_rate': float(win_rate),
            }

        return results

    def generate_sensitivity_heatmap_data(self, param1: str, param1_range: list,
                                          param2: str, param2_range: list) -> pd.DataFrame:
        """
        Generate 2D grid of Sharpe values for heatmap visualization.
        Tests all combinations of param1 x param2 values.
        Returns DataFrame with param1 values as index, param2 values as columns, Sharpe as values.
        """
        results_matrix = np.zeros((len(param1_range), len(param2_range)))

        for i, v1 in enumerate(param1_range):
            for j, v2 in enumerate(param2_range):
                params = self.optimal_params.copy()
                params[param1] = v1
                params[param2] = v2

                try:
                    metrics = self.objective_fn(params)
                    results_matrix[i, j] = metrics.get('sharpe', 0.0)
                except Exception:
                    results_matrix[i, j] = np.nan

        heatmap_df = pd.DataFrame(
            results_matrix,
            index=param1_range,
            columns=param2_range,
        )
        heatmap_df.index.name = param1
        heatmap_df.columns.name = param2

        return heatmap_df


class StrategyOptimizer:
    """Main optimizer that orchestrates all optimization steps."""

    def __init__(self, data: pd.DataFrame, strategy_fn: Callable):
        """
        data: OHLCV DataFrame
        strategy_fn: function(data, params_dict) -> dict with metrics
        """
        self.data = data
        self.strategy_fn = strategy_fn

    def run_full_optimization(self) -> dict:
        """
        Execute complete optimization pipeline:
        1. Grid search on core params
        2. Bayesian refinement of top 10 sets
        3. Walk-forward validation
        4. Robustness testing

        Returns comprehensive results dict.
        """
        # Define parameter grid
        param_grid = {
            'ema_fast': [20, 50, 100],
            'ema_slow': [100, 150, 200],
            'rsi_oversold': [25, 30, 35],
            'rsi_overbought': [65, 70, 75],
            'atr_sl_mult': [1.5, 2.0, 2.5, 3.0],
            'atr_tp_mult': [2.0, 3.0, 4.0],
            'adx_trend_threshold': [20, 25, 30],
            'supertrend_mult': [2.0, 2.5, 3.0, 3.5],
        }

        # ----------------------------------------------------------------
        # Step 1: Grid Search
        # ----------------------------------------------------------------
        # Wrap strategy_fn so it only needs params (data is bound)
        def objective_fn(params: dict) -> dict:
            return self.strategy_fn(self.data, params)

        grid_optimizer = GridSearchOptimizer(objective_fn, param_grid)
        grid_results = grid_optimizer.run(
            maximize='sharpe',
            constraint={'max_dd': ('<=', 0.30)},
        )

        # ----------------------------------------------------------------
        # Step 2: Bayesian Refinement on top 10 parameter sets
        # ----------------------------------------------------------------
        # Build a refined search space around the top 10 results
        if len(grid_results) >= 1:
            top_n = min(10, len(grid_results))
            top_rows = grid_results.head(top_n)

            # Derive bounds from the top sets with some expansion
            param_space = {}
            for param_name in param_grid.keys():
                if param_name in top_rows.columns:
                    vals = top_rows[param_name].values
                    lo = float(np.min(vals))
                    hi = float(np.max(vals))
                    spread = hi - lo if hi > lo else abs(lo) * 0.2
                    margin = spread * 0.25
                    param_space[param_name] = (lo - margin, hi + margin)
                else:
                    grid_vals = param_grid[param_name]
                    param_space[param_name] = (float(min(grid_vals)), float(max(grid_vals)))

            bayesian_opt = BayesianOptimizer(objective_fn, param_space, n_initial=10)
            bayesian_result = bayesian_opt.optimize(
                n_iterations=50,
                maximize='sharpe',
                constraint={'max_dd': ('<=', 0.30)},
            )
        else:
            # Fallback if grid search returned nothing
            param_space = {k: (float(min(v)), float(max(v))) for k, v in param_grid.items()}
            bayesian_opt = BayesianOptimizer(objective_fn, param_space, n_initial=10)
            bayesian_result = bayesian_opt.optimize(n_iterations=50, maximize='sharpe')

        # ----------------------------------------------------------------
        # Step 3: Walk-Forward Validation
        # ----------------------------------------------------------------
        wf_optimizer = WalkForwardOptimizer(
            data=self.data,
            strategy_fn=self.strategy_fn,
            is_window=252,
            oos_window=63,
        )
        wf_results = wf_optimizer.run(param_grid, maximize='sharpe')

        # ----------------------------------------------------------------
        # Step 4: Robustness Testing
        # ----------------------------------------------------------------
        best_params = bayesian_result.best_params
        robustness = RobustnessAnalyzer(objective_fn, best_params)
        sensitivity = robustness.parameter_sensitivity(perturbation=0.20)

        # Generate heatmap data for two key parameters
        heatmap_data = {}
        heatmap_pairs = [
            ('ema_fast', [15, 20, 30, 40, 50, 60, 80, 100],
             'ema_slow', [80, 100, 120, 150, 175, 200, 225]),
            ('atr_sl_mult', [1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
             'atr_tp_mult', [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]),
        ]
        for p1, r1, p2, r2 in heatmap_pairs:
            key = f'{p1}_vs_{p2}'
            heatmap_data[key] = robustness.generate_sensitivity_heatmap_data(p1, r1, p2, r2)

        # Determine overall robustness
        robust_params = [v['is_robust'] for v in sensitivity.values()]
        overall_robust = all(robust_params) if robust_params else False

        return {
            'grid_search': {
                'results': grid_results,
                'n_combinations_tested': len(grid_results),
                'best_params': dict(grid_results.iloc[0]) if len(grid_results) > 0 else {},
            },
            'bayesian': {
                'best_params': bayesian_result.best_params,
                'best_score': bayesian_result.best_score,
                'all_results': bayesian_result.all_results,
                'n_iterations': len(bayesian_result.all_results),
            },
            'walk_forward': {
                'windows': wf_results['windows'],
                'pct_profitable_oos': wf_results['pct_profitable_oos'],
                'combined_oos_sharpe': wf_results['combined_oos_sharpe'],
                'combined_oos_equity': wf_results['combined_oos_equity'],
                'n_windows': len(wf_results['windows']),
            },
            'robustness': {
                'sensitivity': sensitivity,
                'heatmaps': heatmap_data,
                'overall_robust': overall_robust,
            },
            'recommended_params': bayesian_result.best_params,
            'recommendation': (
                'APPROVED - Parameters are robust and walk-forward validated'
                if overall_robust and wf_results['pct_profitable_oos'] >= 0.5
                else 'CAUTION - Parameters may be overfit or fragile; review sensitivity and WF results'
            ),
        }


def _erf_approx(x: float) -> float:
    """
    Approximate the error function erf(x) using Abramowitz & Stegun formula 7.1.26.
    Max error ~1.5e-7.
    """
    sign = 1.0 if x >= 0 else -1.0
    x = abs(x)
    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911

    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * np.exp(-x * x)
    return sign * y
