#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
15_models_drivers.py
Inferential regression models for EII drivers analysis.

This script implements:
1. Counterfactual test: EII ~ inside_outside + PA_type + elevation
   (OLS with cluster-robust SE by PA)
2. Drivers model: functional ~ elevation + fire + ndvi_trend + cropland +
   built_up + hmi + inside_outside
3. RandomForest: Variable importance for EII drivers

Models use statsmodels with cluster-robust standard errors and
scikit-learn RandomForestRegressor for variable importance.

Outputs:
- 03_results/tables/table6_models_coefficients.csv
- 03_results/tables/table6b_models_diagnostics.csv
- 03_results/tables/table6c_rf_importance.csv
- 03_results/figures/fig5_inside_outside_effect.png
- 03_results/figures/fig6_driver_effects.png
- 03_results/figures/fig6b_rf_importance.png
- 05_reproducibility/validation/modeling_notes.txt

Version History:
    1.0.0 - Initial implementation
    1.1.0 - Added RandomForest variable importance
"""

__version__ = "1.1.0"

import argparse
import sys
import json
import warnings
from pathlib import Path
from datetime import datetime

# Add parent directory for shared imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from _shared.config import CONFIG, get_path
from _shared.logging_utils import setup_logger, log_session_info
from _shared.io_utils import ensure_dir, save_dataframe, write_success_marker
from _shared.error_utils import (
    ErrorBundle, write_error_bundle, create_validation_report
)

# Import statsmodels
try:
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    from statsmodels.stats.outliers_influence import variance_inflation_factor
    STATSMODELS_AVAILABLE = True
except ImportError:
    STATSMODELS_AVAILABLE = False
    warnings.warn("statsmodels not installed. OLS models will not run.")

# Import sklearn for RandomForest
try:
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import cross_val_score
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    warnings.warn("scikit-learn not installed. RandomForest will not run.")


# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_NAME = "15_models_drivers"
RANDOM_SEED = CONFIG["model_sampling"]["random_seed"]
FIGURE_DPI = CONFIG["figure_dpi"]


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run inferential regression models for EII drivers"
    )
    parser.add_argument(
        "--base-dir",
        type=str,
        default=None,
        help="Override base project directory"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files"
    )
    parser.add_argument(
        "--allow-pa-count-mismatch",
        action="store_true",
        help="Allow PA count different from expected 19"
    )
    parser.add_argument(
        "--enable-exports",
        action="store_true",
        help="Not used in this script"
    )
    parser.add_argument(
        "--enable-method-compare",
        action="store_true",
        help="Not used in this script"
    )
    parser.add_argument(
        "--allow-geometry-simplification",
        action="store_true",
        help="Not used in this script"
    )
    return parser.parse_args()


def load_model_data(base_dir, logger):
    """
    Load point sample data for modeling.

    Args:
        base_dir: Base directory
        logger: Logger instance

    Returns:
        pandas DataFrame
    """
    tables_dir = get_path("tables", base_dir)
    data_path = tables_dir / "model_points_eii_covariates.csv"

    if not data_path.exists():
        raise FileNotFoundError(
            f"Model points not found: {data_path}\n"
            f"Run 14_sample_points_for_models.py first."
        )

    logger.info(f"Loading model data from: {data_path}")
    df = pd.read_csv(data_path)
    logger.info(f"Loaded {len(df)} observations")

    return df


def prepare_model_data(df, logger):
    """
    Prepare data for modeling: handle missing values, create dummies.

    Args:
        df: Raw data DataFrame
        logger: Logger instance

    Returns:
        Cleaned DataFrame ready for modeling
    """
    logger.info("Preparing data for modeling...")

    # Create a copy
    model_df = df.copy()

    # Define key columns
    outcome_cols = ['eii', 'functional_integrity', 'structural_integrity', 'compositional_integrity']
    predictor_cols = ['inside_outside', 'elevation', 'hmi', 'forest_loss', 'ndvi_trend',
                      'fire_frequency', 'cropland', 'built_up', 'treecover2000', 'ndvi_mean']
    id_cols = ['PA_name', 'PA_type', 'location']

    # Check which columns exist
    available_outcomes = [c for c in outcome_cols if c in model_df.columns]
    available_predictors = [c for c in predictor_cols if c in model_df.columns]

    logger.info(f"Available outcomes: {available_outcomes}")
    logger.info(f"Available predictors: {available_predictors}")

    # Drop rows with missing values in key columns
    key_cols = available_outcomes + available_predictors + id_cols
    key_cols = [c for c in key_cols if c in model_df.columns]

    initial_n = len(model_df)
    model_df = model_df.dropna(subset=key_cols)
    final_n = len(model_df)

    if initial_n != final_n:
        logger.warning(f"Dropped {initial_n - final_n} rows with missing values")

    # Create PA type dummies
    if 'PA_type' in model_df.columns:
        pa_type_dummies = pd.get_dummies(model_df['PA_type'], prefix='type', drop_first=True)
        # Sanitize column names: replace spaces with underscores for patsy formula compatibility
        pa_type_dummies.columns = [c.replace(' ', '_') for c in pa_type_dummies.columns]
        model_df = pd.concat([model_df, pa_type_dummies], axis=1)
        logger.info(f"Created PA type dummies: {list(pa_type_dummies.columns)}")

    # Create PA cluster ID for robust SE
    if 'PA_name' in model_df.columns:
        model_df['pa_cluster'] = pd.factorize(model_df['PA_name'])[0]

    logger.info(f"Final sample size: {len(model_df)}")
    return model_df


def compute_vif(X, logger):
    """
    Compute Variance Inflation Factors.

    Args:
        X: Design matrix (DataFrame)
        logger: Logger instance

    Returns:
        DataFrame with VIF values
    """
    logger.info("Computing Variance Inflation Factors...")

    vif_data = []
    for i, col in enumerate(X.columns):
        try:
            vif = variance_inflation_factor(X.values, i)
            vif_data.append({'variable': col, 'VIF': vif})
        except Exception as e:
            logger.warning(f"Could not compute VIF for {col}: {e}")
            vif_data.append({'variable': col, 'VIF': np.nan})

    vif_df = pd.DataFrame(vif_data)
    return vif_df


def run_counterfactual_model(model_df, logger):
    """
    Run counterfactual model: EII ~ inside_outside + PA_type + elevation.

    Args:
        model_df: Prepared data
        logger: Logger instance

    Returns:
        tuple: (results object, coefficients DataFrame)
    """
    logger.info("\n" + "=" * 60)
    logger.info("MODEL 1: COUNTERFACTUAL TEST")
    logger.info("EII ~ inside_outside + PA_type + elevation")
    logger.info("=" * 60)

    # Build formula
    # Get PA type dummy columns
    type_cols = [c for c in model_df.columns if c.startswith('type_')]

    if type_cols:
        type_terms = ' + '.join(type_cols)
        formula = f"eii ~ inside_outside + {type_terms} + elevation"
    else:
        formula = "eii ~ inside_outside + elevation"

    logger.info(f"Formula: {formula}")

    # Fit OLS with cluster-robust SE
    model = smf.ols(formula, data=model_df).fit(
        cov_type='cluster',
        cov_kwds={'groups': model_df['pa_cluster']}
    )

    logger.info("\nModel Summary:")
    logger.info(f"  R-squared: {model.rsquared:.4f}")
    logger.info(f"  Adj. R-squared: {model.rsquared_adj:.4f}")
    logger.info(f"  F-statistic: {model.fvalue:.2f}")
    logger.info(f"  N observations: {model.nobs}")

    # Extract coefficients
    coef_df = pd.DataFrame({
        'variable': model.params.index,
        'coefficient': model.params.values,
        'std_error': model.bse.values,
        't_stat': model.tvalues.values,
        'p_value': model.pvalues.values,
        'ci_lower': model.conf_int()[0].values,
        'ci_upper': model.conf_int()[1].values,
    })

    coef_df['model'] = 'counterfactual'
    coef_df['significant'] = coef_df['p_value'] < 0.05

    logger.info("\nCoefficients:")
    for _, row in coef_df.iterrows():
        sig = "*" if row['significant'] else ""
        logger.info(f"  {row['variable']}: {row['coefficient']:.4f} ({row['std_error']:.4f}){sig}")

    return model, coef_df


def run_drivers_model(model_df, logger):
    """
    Run drivers model: functional ~ predictors.

    Args:
        model_df: Prepared data
        logger: Logger instance

    Returns:
        tuple: (results object, coefficients DataFrame)
    """
    logger.info("\n" + "=" * 60)
    logger.info("MODEL 2: DRIVERS OF FUNCTIONAL INTEGRITY")
    logger.info("functional ~ elevation + fire + ndvi_trend + cropland + built_up + hmi + inside_outside")
    logger.info("=" * 60)

    # Build formula with available predictors
    predictors = ['elevation', 'fire_frequency', 'ndvi_trend', 'cropland',
                  'built_up', 'hmi', 'inside_outside']
    available = [p for p in predictors if p in model_df.columns]

    if 'functional_integrity' not in model_df.columns:
        logger.warning("functional_integrity not available, using eii as outcome")
        outcome = 'eii'
    else:
        outcome = 'functional_integrity'

    formula = f"{outcome} ~ " + " + ".join(available)
    logger.info(f"Formula: {formula}")

    # Fit OLS with cluster-robust SE
    model = smf.ols(formula, data=model_df).fit(
        cov_type='cluster',
        cov_kwds={'groups': model_df['pa_cluster']}
    )

    logger.info("\nModel Summary:")
    logger.info(f"  R-squared: {model.rsquared:.4f}")
    logger.info(f"  Adj. R-squared: {model.rsquared_adj:.4f}")
    logger.info(f"  F-statistic: {model.fvalue:.2f}")
    logger.info(f"  N observations: {model.nobs}")

    # Extract coefficients
    coef_df = pd.DataFrame({
        'variable': model.params.index,
        'coefficient': model.params.values,
        'std_error': model.bse.values,
        't_stat': model.tvalues.values,
        'p_value': model.pvalues.values,
        'ci_lower': model.conf_int()[0].values,
        'ci_upper': model.conf_int()[1].values,
    })

    coef_df['model'] = 'drivers'
    coef_df['significant'] = coef_df['p_value'] < 0.05

    logger.info("\nCoefficients:")
    for _, row in coef_df.iterrows():
        sig = "*" if row['significant'] else ""
        logger.info(f"  {row['variable']}: {row['coefficient']:.4f} ({row['std_error']:.4f}){sig}")

    return model, coef_df


def create_diagnostics_table(model1, model2, model_df, logger):
    """
    Create model diagnostics table.

    Args:
        model1: Counterfactual model results
        model2: Drivers model results
        model_df: Model data
        logger: Logger instance

    Returns:
        DataFrame with diagnostics
    """
    logger.info("Creating diagnostics table...")

    diagnostics = []

    # Model 1 diagnostics
    diagnostics.append({
        'model': 'counterfactual',
        'n_observations': int(model1.nobs),
        'n_clusters': len(model_df['pa_cluster'].unique()),
        'r_squared': model1.rsquared,
        'adj_r_squared': model1.rsquared_adj,
        'f_statistic': model1.fvalue,
        'f_pvalue': model1.f_pvalue,
        'aic': model1.aic,
        'bic': model1.bic,
        'log_likelihood': model1.llf,
    })

    # Model 2 diagnostics
    diagnostics.append({
        'model': 'drivers',
        'n_observations': int(model2.nobs),
        'n_clusters': len(model_df['pa_cluster'].unique()),
        'r_squared': model2.rsquared,
        'adj_r_squared': model2.rsquared_adj,
        'f_statistic': model2.fvalue,
        'f_pvalue': model2.f_pvalue,
        'aic': model2.aic,
        'bic': model2.bic,
        'log_likelihood': model2.llf,
    })

    return pd.DataFrame(diagnostics)


def run_random_forest_model(model_df, logger):
    """
    Run RandomForest model for variable importance analysis.

    Args:
        model_df: Prepared data
        logger: Logger instance

    Returns:
        tuple: (model, importance DataFrame, diagnostics dict)
    """
    logger.info("\n" + "=" * 60)
    logger.info("MODEL 3: RANDOM FOREST VARIABLE IMPORTANCE")
    logger.info("=" * 60)

    if not SKLEARN_AVAILABLE:
        logger.warning("sklearn not available, skipping RandomForest")
        return None, None, None

    # Define predictors and outcome
    predictors = ['inside_outside', 'elevation', 'hmi', 'forest_loss', 'ndvi_trend',
                  'fire_frequency', 'cropland', 'built_up', 'treecover2000', 'ndvi_mean']
    available = [p for p in predictors if p in model_df.columns]

    if 'eii' not in model_df.columns:
        logger.warning("EII column not found, skipping RandomForest")
        return None, None, None

    # Prepare data
    X = model_df[available].copy()
    y = model_df['eii'].copy()

    # Drop rows with missing values
    valid_mask = X.notna().all(axis=1) & y.notna()
    X = X[valid_mask]
    y = y[valid_mask]

    logger.info(f"Training data: {len(X)} observations, {len(available)} features")
    logger.info(f"Features: {available}")

    # Scale features for better performance
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Fit RandomForest
    rf = RandomForestRegressor(
        n_estimators=500,
        max_depth=10,
        min_samples_split=10,
        min_samples_leaf=5,
        random_state=RANDOM_SEED,
        n_jobs=-1
    )

    rf.fit(X_scaled, y)

    # Cross-validation score
    cv_scores = cross_val_score(rf, X_scaled, y, cv=5, scoring='r2')
    logger.info(f"\nCross-validation R² scores: {cv_scores}")
    logger.info(f"Mean CV R²: {cv_scores.mean():.4f} (+/- {cv_scores.std() * 2:.4f})")

    # Feature importance
    importance_df = pd.DataFrame({
        'variable': available,
        'importance': rf.feature_importances_,
        'importance_pct': rf.feature_importances_ * 100
    }).sort_values('importance', ascending=False)

    importance_df['rank'] = range(1, len(importance_df) + 1)
    importance_df['model'] = 'random_forest'

    logger.info("\nFeature Importance (Top 10):")
    for _, row in importance_df.head(10).iterrows():
        logger.info(f"  {row['rank']}. {row['variable']}: {row['importance_pct']:.2f}%")

    # Model diagnostics
    y_pred = rf.predict(X_scaled)
    train_r2 = rf.score(X_scaled, y)

    # Calculate RMSE
    rmse = np.sqrt(np.mean((y - y_pred) ** 2))

    diagnostics = {
        'model': 'random_forest',
        'n_observations': len(X),
        'n_features': len(available),
        'n_estimators': 500,
        'max_depth': 10,
        'train_r_squared': train_r2,
        'cv_r_squared_mean': cv_scores.mean(),
        'cv_r_squared_std': cv_scores.std(),
        'rmse': rmse,
    }

    logger.info(f"\nModel Performance:")
    logger.info(f"  Training R²: {train_r2:.4f}")
    logger.info(f"  CV R² (mean): {cv_scores.mean():.4f}")
    logger.info(f"  RMSE: {rmse:.4f}")

    return rf, importance_df, diagnostics


def plot_rf_importance(importance_df, output_path, logger):
    """
    Plot RandomForest feature importance.

    Args:
        importance_df: DataFrame with feature importance
        output_path: Path to save figure
        logger: Logger instance
    """
    logger.info("Creating RandomForest importance plot...")

    if importance_df is None or len(importance_df) == 0:
        logger.warning("No importance data to plot")
        return

    # Sort by importance
    df_sorted = importance_df.sort_values('importance', ascending=True)

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 8))

    # Color gradient based on importance
    colors = plt.cm.RdYlGn(np.linspace(0.2, 0.8, len(df_sorted)))

    bars = ax.barh(
        range(len(df_sorted)),
        df_sorted['importance_pct'],
        color=colors,
        edgecolor='black',
        linewidth=0.5,
        alpha=0.8
    )

    ax.set_yticks(range(len(df_sorted)))
    ax.set_yticklabels(df_sorted['variable'], fontsize=10)

    ax.set_xlabel('Relative Importance (%)', fontsize=12)
    ax.set_ylabel('Predictor Variable', fontsize=12)
    ax.set_title(
        'RandomForest Variable Importance for EII\n'
        '(500 trees, 5-fold CV)',
        fontsize=13,
        fontweight='bold'
    )

    # Add percentage labels
    for i, (_, row) in enumerate(df_sorted.iterrows()):
        ax.annotate(
            f'{row["importance_pct"]:.1f}%',
            xy=(row['importance_pct'] + 0.5, i),
            va='center',
            fontsize=9
        )

    ax.grid(axis='x', alpha=0.3)
    ax.set_xlim(0, df_sorted['importance_pct'].max() * 1.15)

    plt.tight_layout()

    fig.savefig(output_path, dpi=FIGURE_DPI, bbox_inches='tight', facecolor='white')
    plt.close(fig)

    logger.info(f"Saved: {output_path}")


def plot_inside_outside_effect(coef_df, output_path, logger):
    """
    Plot inside/outside effect from counterfactual model.

    Args:
        coef_df: Coefficients DataFrame
        output_path: Path to save figure
        logger: Logger instance
    """
    logger.info("Creating inside/outside effect plot...")

    # Filter to counterfactual model
    cf_coef = coef_df[coef_df['model'] == 'counterfactual'].copy()

    # Remove intercept
    cf_coef = cf_coef[cf_coef['variable'] != 'Intercept']

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 6))

    # Plot coefficients with error bars
    y_pos = range(len(cf_coef))
    colors = ['green' if c > 0 else 'red' for c in cf_coef['coefficient']]

    ax.barh(y_pos, cf_coef['coefficient'], xerr=[
        cf_coef['coefficient'] - cf_coef['ci_lower'],
        cf_coef['ci_upper'] - cf_coef['coefficient']
    ], color=colors, alpha=0.7, capsize=4, edgecolor='black', linewidth=0.5)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(cf_coef['variable'])
    ax.axvline(0, color='black', linestyle='--', linewidth=0.8)

    ax.set_xlabel('Coefficient Estimate', fontsize=11)
    ax.set_ylabel('Variable', fontsize=11)
    ax.set_title(
        'Counterfactual Model: Effect on EII\n'
        '(OLS with cluster-robust SE)',
        fontsize=12,
        fontweight='bold'
    )

    # Add significance markers
    for i, (_, row) in enumerate(cf_coef.iterrows()):
        if row['significant']:
            ax.annotate('*', xy=(row['coefficient'], i), fontsize=14, fontweight='bold')

    ax.grid(axis='x', alpha=0.3)
    plt.tight_layout()

    fig.savefig(output_path, dpi=FIGURE_DPI, bbox_inches='tight', facecolor='white')
    plt.close(fig)

    logger.info(f"Saved: {output_path}")


def plot_driver_effects(coef_df, output_path, logger):
    """
    Plot driver effects from drivers model.

    Args:
        coef_df: Coefficients DataFrame
        output_path: Path to save figure
        logger: Logger instance
    """
    logger.info("Creating driver effects plot...")

    # Filter to drivers model
    drv_coef = coef_df[coef_df['model'] == 'drivers'].copy()

    # Remove intercept
    drv_coef = drv_coef[drv_coef['variable'] != 'Intercept']

    # Sort by absolute coefficient
    drv_coef = drv_coef.sort_values('coefficient', key=abs, ascending=True)

    # Create figure
    fig, ax = plt.subplots(figsize=(10, 8))

    y_pos = range(len(drv_coef))
    colors = ['green' if c > 0 else 'red' for c in drv_coef['coefficient']]

    ax.barh(y_pos, drv_coef['coefficient'], xerr=[
        drv_coef['coefficient'] - drv_coef['ci_lower'],
        drv_coef['ci_upper'] - drv_coef['coefficient']
    ], color=colors, alpha=0.7, capsize=4, edgecolor='black', linewidth=0.5)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(drv_coef['variable'])
    ax.axvline(0, color='black', linestyle='--', linewidth=0.8)

    ax.set_xlabel('Coefficient Estimate', fontsize=11)
    ax.set_ylabel('Predictor', fontsize=11)
    ax.set_title(
        'Drivers Model: Effects on Functional Integrity\n'
        '(OLS with cluster-robust SE)',
        fontsize=12,
        fontweight='bold'
    )

    # Add significance markers
    for i, (_, row) in enumerate(drv_coef.iterrows()):
        if row['significant']:
            x_pos = row['coefficient'] + (0.01 if row['coefficient'] > 0 else -0.01)
            ax.annotate('*', xy=(x_pos, i), fontsize=14, fontweight='bold')

    ax.grid(axis='x', alpha=0.3)
    plt.tight_layout()

    fig.savefig(output_path, dpi=FIGURE_DPI, bbox_inches='tight', facecolor='white')
    plt.close(fig)

    logger.info(f"Saved: {output_path}")


def write_modeling_notes(output_path, model_df, coef_df, diagnostics_df, rf_diagnostics, logger):
    """
    Write modeling notes for reproducibility.

    Args:
        output_path: Path to save notes
        model_df: Model data
        coef_df: Coefficients
        diagnostics_df: OLS diagnostics
        rf_diagnostics: RandomForest diagnostics dict (or None)
        logger: Logger instance
    """
    with open(output_path, 'w') as f:
        f.write("MODELING NOTES\n")
        f.write("=" * 70 + "\n")
        f.write(f"Script: {SCRIPT_NAME}\n")
        f.write(f"Version: {__version__}\n")
        f.write(f"Timestamp: {datetime.now().isoformat()}\n\n")

        f.write("DATA SUMMARY\n")
        f.write("-" * 70 + "\n")
        f.write(f"Total observations: {len(model_df)}\n")
        f.write(f"Inside PA: {(model_df['inside_outside'] == 1).sum()}\n")
        f.write(f"Outside PA: {(model_df['inside_outside'] == 0).sum()}\n")
        f.write(f"Number of PA clusters: {model_df['pa_cluster'].nunique()}\n\n")

        f.write("MODELS IMPLEMENTED\n")
        f.write("-" * 70 + "\n")
        f.write("1. Counterfactual Model (OLS with cluster-robust SE)\n")
        f.write("   Formula: EII ~ inside_outside + PA_type + elevation\n")
        f.write("   Purpose: Test whether PA protection affects EII\n\n")

        f.write("2. Drivers Model (OLS with cluster-robust SE)\n")
        f.write("   Formula: functional_integrity ~ elevation + fire + ndvi_trend + \n")
        f.write("            cropland + built_up + hmi + inside_outside\n")
        f.write("   Purpose: Identify key drivers of functional integrity\n\n")

        f.write("3. RandomForest Model (scikit-learn)\n")
        f.write("   Target: EII\n")
        f.write("   Purpose: Variable importance analysis (non-linear relationships)\n")
        f.write("   Parameters: 500 trees, max_depth=10, 5-fold CV\n\n")

        f.write("NOTES\n")
        f.write("-" * 70 + "\n")
        f.write("- OLS standard errors are cluster-robust by PA\n")
        f.write("- RandomForest provides complementary variable importance\n")
        f.write(f"- Random seed: {RANDOM_SEED}\n")
        f.write("- * indicates p < 0.05 for OLS models\n\n")

        f.write("MODEL DIAGNOSTICS\n")
        f.write("-" * 70 + "\n")

        # OLS models
        for _, row in diagnostics_df.iterrows():
            f.write(f"\n{row['model'].upper()} MODEL (OLS):\n")
            f.write(f"  N: {row['n_observations']}\n")
            f.write(f"  R-squared: {row['r_squared']:.4f}\n")
            f.write(f"  Adj. R-squared: {row['adj_r_squared']:.4f}\n")
            f.write(f"  AIC: {row['aic']:.2f}\n")
            f.write(f"  BIC: {row['bic']:.2f}\n")

        # RandomForest diagnostics
        if rf_diagnostics is not None:
            f.write(f"\nRANDOM FOREST MODEL:\n")
            f.write(f"  N: {rf_diagnostics['n_observations']}\n")
            f.write(f"  Features: {rf_diagnostics['n_features']}\n")
            f.write(f"  Training R-squared: {rf_diagnostics['train_r_squared']:.4f}\n")
            f.write(f"  CV R-squared (mean): {rf_diagnostics['cv_r_squared_mean']:.4f}\n")
            f.write(f"  CV R-squared (std): {rf_diagnostics['cv_r_squared_std']:.4f}\n")
            f.write(f"  RMSE: {rf_diagnostics['rmse']:.4f}\n")

        f.write("\n" + "=" * 70 + "\n")

    logger.info(f"Saved modeling notes: {output_path}")


def main():
    args = parse_args()
    base_dir = args.base_dir

    # Set up logging
    log_dir = get_path("logs", base_dir)
    ensure_dir(log_dir)
    log_file = log_dir / f"{SCRIPT_NAME}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logger = setup_logger(SCRIPT_NAME, log_file)

    log_session_info(logger, SCRIPT_NAME, __version__, args)

    error_bundle = ErrorBundle(SCRIPT_NAME, __version__)
    error_bundle.add_context("base_dir", str(base_dir or get_path("base")))

    try:
        # Check statsmodels
        if not STATSMODELS_AVAILABLE:
            raise ImportError(
                "statsmodels is required for this script. "
                "Install with: pip install statsmodels"
            )

        # Load data
        raw_df = load_model_data(base_dir, logger)

        # Prepare data
        model_df = prepare_model_data(raw_df, logger)

        # Validate PA count
        n_pas = model_df['PA_name'].nunique()
        if n_pas != CONFIG["expected_pa_count"] and not args.allow_pa_count_mismatch:
            logger.warning(
                f"PA count in data ({n_pas}) differs from expected "
                f"({CONFIG['expected_pa_count']})"
            )

        # Set random seed
        np.random.seed(RANDOM_SEED)

        # Run models
        logger.info("\n" + "=" * 60)
        logger.info("RUNNING REGRESSION MODELS")
        logger.info("=" * 60)

        # Model 1: Counterfactual
        model1, coef1 = run_counterfactual_model(model_df, logger)

        # Model 2: Drivers
        model2, coef2 = run_drivers_model(model_df, logger)

        # Combine coefficients
        all_coef = pd.concat([coef1, coef2], ignore_index=True)

        # Create diagnostics table for OLS models
        diagnostics_df = create_diagnostics_table(model1, model2, model_df, logger)

        # Model 3: RandomForest
        rf_model, rf_importance, rf_diagnostics = run_random_forest_model(model_df, logger)

        # Output paths
        results_tables = get_path("results_tables", base_dir)
        ensure_dir(results_tables)

        figures_dir = get_path("figures", base_dir)
        ensure_dir(figures_dir)

        validation_dir = get_path("validation", base_dir)
        ensure_dir(validation_dir)

        # Save coefficients table
        coef_path = results_tables / "table6_models_coefficients.csv"
        # Round numeric columns
        for col in ['coefficient', 'std_error', 't_stat', 'p_value', 'ci_lower', 'ci_upper']:
            all_coef[col] = all_coef[col].round(6)
        save_dataframe(all_coef, coef_path, overwrite=args.overwrite)
        logger.info(f"Saved coefficients: {coef_path}")

        # Save diagnostics table
        diag_path = results_tables / "table6b_models_diagnostics.csv"
        save_dataframe(diagnostics_df, diag_path, overwrite=args.overwrite)
        logger.info(f"Saved diagnostics: {diag_path}")

        # Save RandomForest importance
        rf_importance_path = None
        fig6b_path = None
        if rf_importance is not None:
            rf_importance_path = results_tables / "table6c_rf_importance.csv"
            save_dataframe(rf_importance, rf_importance_path, overwrite=args.overwrite)
            logger.info(f"Saved RF importance: {rf_importance_path}")

        # Create figures
        fig5_path = figures_dir / "fig5_inside_outside_effect.png"
        plot_inside_outside_effect(all_coef, fig5_path, logger)

        fig6_path = figures_dir / "fig6_driver_effects.png"
        plot_driver_effects(all_coef, fig6_path, logger)

        # RandomForest importance figure
        if rf_importance is not None:
            fig6b_path = figures_dir / "fig6b_rf_importance.png"
            plot_rf_importance(rf_importance, fig6b_path, logger)

        # Write modeling notes
        notes_path = validation_dir / "modeling_notes.txt"
        write_modeling_notes(notes_path, model_df, all_coef, diagnostics_df, rf_diagnostics, logger)

        # Validation report
        checks = {
            "Data loaded": len(raw_df) > 0,
            "Data prepared": len(model_df) > 0,
            "Model 1 (counterfactual) fit": model1 is not None,
            "Model 2 (drivers) fit": model2 is not None,
            "Model 3 (RandomForest) fit": rf_model is not None,
            "Coefficients table created": coef_path.exists(),
            "Diagnostics table created": diag_path.exists(),
            "RF importance table created": rf_importance_path.exists() if rf_importance_path else False,
            "Figure 5 created": fig5_path.exists(),
            "Figure 6 created": fig6_path.exists(),
            "Figure 6b (RF) created": fig6b_path.exists() if fig6b_path else False,
            "Modeling notes created": notes_path.exists(),
        }

        report_path = create_validation_report(
            SCRIPT_NAME, __version__, checks, validation_dir
        )
        logger.info(f"Validation report: {report_path}")

        # Success marker
        script_dir = Path(__file__).parent
        success_path = write_success_marker(script_dir, SCRIPT_NAME)
        logger.info(f"Success marker: {success_path}")

        logger.info("\n" + "=" * 60)
        logger.info("MODELING COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Observations: {len(model_df)}")
        n_models = 3 if rf_model is not None else 2
        logger.info(f"Models fit: {n_models} (counterfactual, drivers, RandomForest)")

        # Key findings
        inside_coef = all_coef[
            (all_coef['model'] == 'counterfactual') &
            (all_coef['variable'] == 'inside_outside')
        ]
        if len(inside_coef) > 0:
            effect = inside_coef.iloc[0]['coefficient']
            sig = "*" if inside_coef.iloc[0]['significant'] else ""
            logger.info(f"Inside/Outside effect on EII: {effect:.4f}{sig}")

        # Top RF predictors
        if rf_importance is not None and len(rf_importance) > 0:
            top_predictor = rf_importance.iloc[0]
            logger.info(f"Top RF predictor: {top_predictor['variable']} ({top_predictor['importance_pct']:.1f}%)")

    except Exception as e:
        logger.error(f"FATAL ERROR: {e}")
        error_bundle.capture_exception(e)
        error_dir = get_path("errors", base_dir)
        error_path = write_error_bundle(error_bundle, error_dir)
        logger.error(f"Error bundle written to: {error_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
