import json
from pathlib import Path

def create_profit_attribution_cells():
    """Create the 9 new cells as proper JSON-serializable dicts"""
    cells = []
    
    # Cell 1: Markdown - Introduction
    cells.append({
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "## 8.5 Profit Attribution Analysis\n",
            "\n",
            "Enhancing our performance analysis with profit attribution to understand what's driving returns.\n",
            "\n",
            "We'll use the new profit attribution functions to decompose performance by:\n",
            "- Factors (momentum, value, quality, etc.)\n",
            "- Market regimes (trend up, trend down, chop)\n",
            "- Models (in our ensemble)\n",
            "\n",
            "This helps identify sources of alpha and inform capital allocation decisions.\n"
        ]
    })
    
    # Cell 2: Code - Profit Attribution Functions & Sample Data Setup
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [
            "# Import profit attribution functions\n",
            "print(\"\\n\ud83d\udcca Importing profit attribution functions...\")\n",
            "\n",
            "# Since we're in a demo environment, we'll define simplified versions of the attribution functions\n",
            "# In practice, you would import from alpha.validation.metrics\n",
            "import pandas as pd\n",
            "import numpy as np\n",
            "from scipy import stats\n",
            "\n",
            "def calculate_ic(predictions, actual_returns, method='pearson'):\n",
            "    \"\"\"Calculate Information Coefficient\"\"\"\n",
            "    if isinstance(predictions, np.ndarray):\n",
            "        predictions = pd.Series(predictions)\n",
            "    if isinstance(actual_returns, np.ndarray):\n",
            "        actual_returns = pd.Series(actual_returns)\n",
            "    \n",
            "    df = pd.DataFrame({'pred': predictions, 'actual': actual_returns}).dropna()\n",
            "    if len(df) < 2:\n",
            "        return 0.0\n",
            "    \n",
            "    if method == 'pearson':\n",
            "        ic = df['pred'].corr(df['actual'], method='pearson')\n",
            "    elif method == 'spearman':\n",
            "        ic = df['pred'].corr(df['actual'], method='spearman')\n",
            "    else:\n",
            "        raise ValueError(\"Method must be 'pearson' or 'spearman'\")\n",
            "    \n",
            "    return ic if not np.isnan(ic) else 0.0\n",
            "\n",
            "def calculate_profit_attribution_by_factor(factor_returns, factor_weights, periods_per_year=252):\n",
            "    \"\"\"Calculate profit attribution by factor (Brinson-style)\"\"\"\n",
            "    common_index = factor_returns.index.intersection(factor_weights.index)\n",
            "    factor_returns = factor_returns.loc[common_index]\n",
            "    factor_weights = factor_weights.loc[common_index]\n",
            "    \n",
            "    if len(common_index) == 0:\n",
            "        return pd.DataFrame(columns=['factor', 'total_return', 'attribution', 'contribution_pct'])\n",
            "    \n",
            "    portfolio_returns = (factor_returns * factor_weights).sum(axis=1)\n",
            "    total_return = (1 + portfolio_returns).prod() - 1\n",
            "    \n",
            "    attribution_data = []\n",
            "    for factor in factor_returns.columns:\n",
            "        factor_ret = factor_returns[factor]\n",
            "        avg_weight = factor_weights[factor].mean()\n",
            "        factor_only_returns = factor_returns[factor] * factor_weights[factor]\n",
            "        factor_total_return = (1 + factor_only_returns).prod() - 1\n",
            "        attribution_data.append({\n",
            "            'factor': factor,\n",
            "            'total_return': factor_total_return,\n",
            "            'attribution': avg_weight * factor_ret.mean() * len(factor_returns),\n",
            "            'contribution_pct': (factor_total_return / total_return * 100) if total_return != 0 else 0\n",
            "        })\n",
            "    \n",
            "    return pd.DataFrame(attribution_data)\n",
            "\n",
            "def calculate_profit_attribution_by_regime(returns, regimes, periods_per_year=252):\n",
            "    \"\"\"Calculate profit attribution by market regime\"\"\"\n",
            "    common_index = returns.index.intersection(regimes.index)\n",
            "    returns = returns.loc[common_index]\n",
            "    regimes = regimes.loc[common_index]\n",
            "    \n",
            "    if len(common_index) == 0:\n",
            "        return pd.DataFrame(columns=['regime', 'total_return', 'annualized_return', 'contribution_pct'])\n",
            "    \n",
            "    total_return = (1 + returns).prod() - 1\n",
            "    \n",
            "    attribution_data = []\n",
            "    for regime in regimes.unique():\n",
            "        regime_returns = returns[regimes == regime]\n",
            "        if len(regime_returns) > 0:\n",
            "            regime_total_return = (1 + regime_returns).prod() - 1\n",
            "            regime_annualized = (1 + regime_total_return) ** (periods_per_year / len(regime_returns)) - 1\n",
            "            attribution_data.append({\n",
            "                'regime': regime,\n",
            "                'total_return': regime_total_return,\n",
            "                'annualized_return': regime_annualized,\n",
            "                'contribution_pct': (regime_total_return / total_return * 100) if total_return != 0 else 0\n",
            "            })\n",
            "    \n",
            "    return pd.DataFrame(attribution_data)\n",
            "\n",
            "def calculate_profit_attribution_by_model(model_predictions, actual_returns, model_weights, periods_per_year=252):\n",
            "    \"\"\"Calculate profit attribution by model\"\"\"\n",
            "    common_index = actual_returns.index\n",
            "    for model_name, preds in model_predictions.items():\n",
            "        common_index = common_index.intersection(preds.index)\n",
            "    \n",
            "    if len(common_index) == 0:\n",
            "        return pd.DataFrame(columns=['model', 'weight', 'ic', 'attribution', 'contribution_pct'])\n",
            "    \n",
            "    actual_returns_aligned = actual_returns.loc[common_index]\n",
            "    \n",
            "    # Calculate IC for each model\n",
            "    model_ics = {}\n",
            "    for model_name, preds in model_predictions.items():\n",
            "        preds_aligned = preds.loc[common_index]\n",
            "        if len(preds_aligned) > 1:\n",
            "            ic = calculate_ic(preds_aligned, actual_returns_aligned)\n",
            "        else:\n",
            "            ic = 0.0\n",
            "        model_ics[model_name] = ic\n",
            "    \n",
            "    total_weighted_ic = sum(model_ics[model] * model_weights.get(model, 0) for model in model_ics)\n",
            "    \n",
            "    attribution_data = []\n",
            "    for model_name in model_ics:\n",
            "        weight = model_weights.get(model_name, 0)\n",
            "        ic = model_ics[model_name]\n",
            "        attribution = ic * weight\n",
            "        attribution_data.append({\n",
            "            'model': model_name,\n",
            "            'weight': weight,\n",
            "            'ic': ic,\n",
            "            'attribution': attribution,\n",
            "            'contribution_pct': (attribution / total_weighted_ic * 100) if total_weighted_ic != 0 else 0\n",
            "        })\n",
            "    \n",
            "    return pd.DataFrame(attribution_data)\n",
            "\n",
            "def calculate_factor_half_life(factor_returns, periods_per_year=252):\n",
            "    \"\"\"Calculate factor edge half-life\"\"\"\n",
            "    if len(factor_returns) < 10:\n",
            "        return periods_per_year\n",
            "    \n",
            "    max_lag = min(len(factor_returns) // 2, 252)\n",
            "    autocorrs = []\n",
            "    \n",
            "    for lag in range(1, max_lag + 1):\n",
            "        if len(factor_returns) > lag:\n",
            "            corr = factor_returns.autocorr(lag=lag)\n",
            "            if not np.isnan(corr):\n",
            "                autocorrs.append(corr)\n",
            "            else:\n",
            "                autocorrs.append(0)\n",
            "        else:\n",
            "            autocorrs.append(0)\n",
            "    \n",
            "    half_life = periods_per_year\n",
            "    for lag, corr in enumerate(autocorrs, 1):\n",
            "        if corr <= 0.5:\n",
            "            half_life = lag\n",
            "            break\n",
            "    \n",
            "    return half_life\n",
            "\n",
            "def calculate_regime_transition_probability(regime_history):\n",
            "    \"\"\"Calculate regime transition probability matrix\"\"\"\n",
            "    # Simplified version without importing RegimeState\n",
            "    regimes = sorted(regime_history.unique())\n",
            "    \n",
            "    if len(regimes) == 0:\n",
            "        return pd.DataFrame()\n",
            "    \n",
            "    transition_counts = pd.DataFrame(0, index=regimes, columns=regimes, dtype=int)\n",
            "    \n",
            "    for i in range(len(regime_history) - 1):\n",
            "        from_regime = regime_history.iloc[i]\n",
            "        to_regime = regime_history.iloc[i + 1]\n",
            "        if from_regime in regimes and to_regime in regimes:\n",
            "            transition_counts.loc[from_regime, to_regime] += 1\n",
            "    \n",
            "    transition_probs = transition_counts.div(transition_counts.sum(axis=1), axis=0)\n",
            "    transition_probs = transition_probs.fillna(0)\n",
            "    \n",
            "    return transition_probs\n",
            "\n",
            "print(\"\\u2705 Profit attribution functions defined\")"
        ]
    })
    
    # Cell 3: Code - Generate Sample Data for Demonstration
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [
            "# Generate sample data for profit attribution demonstration\n",
            "print(\"\\n\ud83d\udcc8 Generating sample data for attribution analysis...\")\n",
            "\n",
            "np.random.seed(42)\n",
            "n_periods = 252  # 1 year of daily data\n",
            "dates = pd.date_range('2023-01-01', periods=n_periods, freq='D')\n",
            "\n",
            "# Generate factor returns (3 factors with different characteristics)\n",
            "factor_returns = pd.DataFrame({\n",
            "    'momentum': np.random.normal(0.0005, 0.015, n_periods),\n",
            "    'value': np.random.normal(0.0003, 0.012, n_periods),\n",
            "    'quality': np.random.normal(0.0004, 0.010, n_periods)\n",
            "}, index=dates)\n",
            "\n",
            "# Add some correlation between factors\n",
            "factor_returns['value'] += 0.3 * factor_returns['momentum']\n",
            "factor_returns['quality'] += 0.2 * factor_returns['momentum'] + 0.2 * factor_returns['value']\n",
            "\n",
            "# Generate factor weights (simplified - equal weight for demo)\n",
            "factor_weights = pd.DataFrame({\n",
            "    'momentum': 0.33,\n",
            "    'value': 0.33,\n",
            "    'quality': 0.34\n",
            "}, index=dates)\n",
            "\n",
            "# Generate regimes (simplified regime detection)\n",
            "trend_signal = factor_returns['momentum'].rolling(20).mean().fillna(0)\n",
            "regimes = pd.Series(\n",
            "    np.where(trend_signal > 0.001, 'trend_up',\n",
            "            np.where(trend_signal < -0.001, 'trend_down', 'chop')),\n",
            "    index=dates\n",
            ")\n",
            "\n",
            "# Generate actual returns (portfolio returns)\n",
            "actual_returns = (factor_returns * factor_weights).sum(axis=1)\n",
            "\n",
            "# Generate model predictions (2 models with different skills)\n",
            "model_predictions = {\n",
            "    'ml_model': pd.Series(\n",
            "        actual_returns.shift(1).fillna(0) + np.random.normal(0, 0.005, n_periods),\n",
            "        index=dates\n",
            "    ),\n",
            "    'factor_model': pd.Series(\n",
            "        (factor_returns * pd.Series([0.4, 0.3, 0.3], index=factor_returns.columns)).sum(axis=1).shift(1).fillna(0),\n",
            "        index=dates\n",
            "    )\n",
            "}\n",
            "\n",
            "# Model weights\n",
            "model_weights = {\n",
            "    'ml_model': 0.6,\n",
            "    'factor_model': 0.4\n",
            "}\n",
            "\n",
            "print(f\"   Generated {len(dates)} periods of sample data\")\n",
            "print(f\"   Date range: {dates[0].date()} to {dates[-1].date()}\")"
        ]
    })
    
    # Cell 4: Code - Factor Attribution Demonstration
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [
            "# 1. Profit Attribution by Factor\n",
            "print(\"\\n1️⃣  Profit Attribution by Factor\")\n",
            "print(\"-\" * 40)\n",
            "\n",
            "factor_attribution = calculate_profit_attribution_by_factor(\n",
            "    factor_returns, \n",
            "    factor_weights\n",
            ")\n",
            "\n",
            "print(factor_attribution.to_string(index=False))\n",
            "\n",
            "# Interpretation\n",
            "print(\"\\n📊 Interpretation:\")\n",
            "print(\"   - Shows how much each factor contributed to total returns\")\n",
            "print(\"   - Helps identify which factors are driving performance\")\n",
            "print(\"   - Can inform factor weighting decisions\")"
        ]
    })
    
    # Cell 5: Code - Regime Attribution Demonstration
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [
            "# 2. Profit Attribution by Regime\n",
            "print(\"\\n2️⃣  Profit Attribution by Regime\")\n",
            "print(\"-\" * 40)\n",
            "\n",
            "regime_attribution = calculate_profit_attribution_by_regime(\n",
            "    actual_returns, \n",
            "    regimes\n",
            ")\n",
            "\n",
            "print(regime_attribution.to_string(index=False))\n",
            "\n",
            "# Interpretation\n",
            "print(\"\\n📊 Interpretation:\")\n",
            "print(\"   - Shows performance in different market environments\")\n",
            "print(\"   - Helps understand strategy robustness across regimes\")\n",
            "print(\"   - Can inform regime-specific adjustments\")"
        ]
    })
    
    # Cell 6: Code - Model Attribution Demonstration
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [
            "# 3. Profit Attribution by Model\n",
            "print(\"\\n3️⃣  Profit Attribution by Model\")\n",
            "print(\"-\" * 40)\n",
            "\n",
            "model_attribution = calculate_profit_attribution_by_model(\n",
            "    model_predictions,\n",
            "    actual_returns,\n",
            "    model_weights\n",
            ")\n",
            "\n",
            "print(model_attribution.to_string(index=False))\n",
            "\n",
            "# Interpretation\n",
            "print(\"\\n📊 Interpretation:\")\n",
            "print(\"   - Shows each model's contribution to ensemble performance\")\n",
            "print(\"   - Helps inform model weighting decisions\")\n",
            "print(\"   - Identifies underperforming models that may need replacement\")"
        ]
    })
    
    # Cell 7: Code - Factor Half-Life Analysis
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [
            "# 4. Factor Half-Life Analysis\n",
            "print(\"\\n4️⃣  Factor Half-Life Analysis\")\n",
            "print(\"-\" * 40)\n",
            "\n",
            "print(\"Factor half-life (estimated decay time):\")\n",
            "for factor in factor_returns.columns:\n",
            "    half_life = calculate_factor_half_life(factor_returns[factor])\n",
            "    print(f\"{factor:10s}: {half_life:3.0f} days\")\n",
            "\n",
            "# Interpretation\n",
            "print(\"\\n📊 Interpretation:\")\n",
            "print(\"   - Shows how long a factor's edge persists before decaying\")\n",
            "print(\"   - Helps identify factors that may need replacement or re calibration\")\n",
            "print(\"   - Shorter half-life = faster decay = needs more frequent updating\")"
        ]
    })
    
    # Cell 8: Code - Regime Transition Probability Matrix
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": [
            "# 5. Regime Transition Probability Matrix\n",
            "print(\"\\n5️⃣  Regime Transition Probability Matrix\")\n",
            "print(\"-\" * 40)\n",
            "\n",
            "transition_prob = calculate_regime_transition_probability(regimes)\n",
            "print(transition_prob.to_string())\n",
            "\n",
            "# Interpretation\n",
            "print(\"\\n📊 Interpretation:\")\n",
            "print(\"   - Shows probability of moving from one regime to another\")\n",
            "print(\"   - Helps improve regime detection models\")\n",
            "print(\"   - Informs expected holding period calculations\")\n",
            "print(\"   - Higher diagonal values = more persistent regimes\")"
        ]
    })
    
    # Cell 9: Markdown - Key Insights Summary
    cells.append({
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "## 8.6 Key Insights from Profit Attribution\n",
            "\n",
            "The profit attribution analysis provides valuable insights for strategy improvement:\n",
            "\n",
            "### 🔍 What We Learned\n",
            "\n",
            "1. **Factor Attribution**: Identifies which factors (momentum, value, quality) are driving returns\n",
            "2. **Regime Attribution**: Shows how strategy performs in different market environments\n",
            "3. **Model Attribution**: Quantifies each model's contribution to ensemble performance\n",
            "4. **Factor Half-Life**: Measures how quickly factor signals decay over time\n",
            "5. **Regime Transitions**: Shows likelihood of regime changes\n",
            "\n",
            "### 🎯 How to Use These Insights\n",
            "\n",
            "- **Capital Allocation**: Increase allocation to high-performing factors/models\n",
            "- **Risk Management**: Reduce exposure to decaying factors or challenging regimes\n",
            "- **Model Improvement**: Focus on improving or replacing underperforming models\n",
            "- **Regime Adaptation**: Adjust strategy parameters based on regime persistence\n",
            "- **Timely Rebalancing**: Use half-life and transition probabilities to inform rebalancing frequency\n",
            "\n",
            "---\n",
            "*Profit attribution completes our performance analysis toolkit, enabling data-driven strategy optimization*\n"
        ]
    })
    
    return cells

def main():
    notebook_path = Path("/Users/aryanagarwal/alpha-system/kaggle-alpha-push/alpha_model.ipynb")
    
    # Read existing notebook
    with open(notebook_path, 'r') as f:
        notebook = json.load(f)
    
    # Find insertion index (after section 8, before section 9)
    # Section 8 is at index 13 (0-based), Section 9 at index 14
    insertion_idx = 14  # Insert before cell 14 (section 9)
    
    # Create new cells
    new_cells = create_profit_attribution_cells()
    
    # Insert cells
    notebook['cells'][insertion_idx:insertion_idx] = new_cells
    
    # Write back with proper formatting
    with open(notebook_path, 'w') as f:
        json.dump(notebook, f, indent=2, ensure_ascii=False)
    
    print(f"Added {len(new_cells)} cells at index {insertion_idx}")
    print("Notebook updated successfully!")

if __name__ == "__main__":
    main()