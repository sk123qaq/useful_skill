#!/usr/bin/env python3
from __future__ import annotations

from typing import Any
import pandas as pd
from sklearn.model_selection import train_test_split
from model_catalog import get_model_catalog, get_model_spec
from preprocessing import encode_categoricals

def fit_selected_model(
    df: pd.DataFrame, 
    target: str, 
    task: str, 
    model_name: str | None = None, 
    test_size: float = 0.2, 
    random_state: int = 42
) -> dict[str, Any]:
    """
    Fits a supervised model for explainability analysis.
    This is a simplified version of the model fitting pipeline that ensures
    numeric features and a fitted estimator are returned for SHAP and PDP.
    """
    if task not in {"classification", "regression"}:
        raise ValueError(f"Unsupported task for model fitting: {task}")

    # 1. Prepare Features
    # Drop rows with missing target
    if target not in df.columns:
        raise ValueError(f"Target column '{target}' not found in dataframe.")
        
    model_df = df.dropna(subset=[target]).copy()
    y = model_df[target]
    
    # Drop columns that are not features (like target)
    X_raw = model_df.drop(columns=[target])
    
    # Identify and drop other non-feature columns if they exist (e.g. weight_col if passed)
    # But for explainability we usually just want everything else encoded.
    
    # Simple encoding using the preprocessing module
    X = encode_categoricals(X_raw)
    
    # Basic imputation for features to ensure numeric compatibility for all models
    # Select only numeric columns for fillna(0) to avoid issues, 
    # though encode_categoricals should have handled strings.
    X = X.select_dtypes(include=["number", "bool"]).fillna(0).astype(float)
    
    # 2. Select Model
    try:
        if model_name:
            spec = get_model_spec(task, model_name, include_tuning=True)
        else:
            # Default to the first non-dummy model if available
            catalog = get_model_catalog(task)
            non_dummy = [s for s in catalog if s.family != "dummy"]
            spec = non_dummy[0] if non_dummy else catalog[0]
    except Exception:
        # Fallback if catalog fails or model not found
        catalog = get_model_catalog(task)
        spec = catalog[-1] # Usually Random Forest in our catalogs
    
    model = spec.builder()
    
    # 3. Train/Test Split
    # Stratify for classification if classes have enough samples
    stratify = None
    if task == "classification":
        class_counts = y.value_counts()
        if (class_counts >= 2).all():
            stratify = y
            
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=stratify
    )
    
    # 4. Fit
    model.fit(X_train, y_train)
    
    return {
        "model_name": spec.name,
        "model": model,
        "X_train": X_train,
        "X_test": X_test,
        "y_train": y_train,
        "y_test": y_test,
        "feature_names": list(X.columns),
    }
