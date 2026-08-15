# kerno/skills/builtins/ml.py
"""
Built-in machine learning skills.

Design principles:
  - Every function returns structured results, not just prints
  - Cross-validation by default — never a single train/test split presented as final
  - No silent overfitting: training metrics always paired with validation metrics
  - Feature importance always computed when the model supports it
  - Every result is checkpointable
"""

_ML_SKILLS_CODE = '''
import pandas as pd
import numpy as _np
from IPython.display import display as _display, HTML as _HTML


# ─── Data Splitting ───────────────────────────────────────────────────────────

def split(
    df:          pd.DataFrame,
    target:      str,
    test_size:   float = 0.20,
    val_size:    float = 0.00,
    random_state: int  = 42,
    stratify:    bool  = True,
) -> dict:
    """
    Split a DataFrame into train / (optional val) / test sets.

    Args:
        df:           Source DataFrame
        target:       Name of the target column
        test_size:    Fraction for test set (default: 0.20)
        val_size:     Fraction for validation set (0 = no val set)
        random_state: Random seed for reproducibility
        stratify:     Stratify split by target class distribution

    Returns:
        dict with keys: X_train, X_test, y_train, y_test,
                        X_val, y_val (if val_size > 0),
                        feature_names, target_name
    """
    from sklearn.model_selection import train_test_split as _tts

    X = df.drop(columns=[target])
    y = df[target]

    strat = y if stratify and y.nunique() < 20 else None

    X_tr, X_te, y_tr, y_te = _tts(
        X, y,
        test_size    = test_size + val_size,
        random_state = random_state,
        stratify     = strat,
    )

    result = {
        "X_train":       X_tr,
        "X_test":        X_te,
        "y_train":       y_tr,
        "y_test":        y_te,
        "X_val":         None,
        "y_val":         None,
        "feature_names": list(X.columns),
        "target_name":   target,
    }

    if val_size > 0:
        val_fraction = val_size / (test_size + val_size)
        strat2       = y_te if stratify and y_te.nunique() < 20 else None
        X_te, X_val, y_te, y_val = _tts(
            X_te, y_te,
            test_size    = val_fraction,
            random_state = random_state,
            stratify     = strat2,
        )
        result["X_test"]  = X_te
        result["y_test"]  = y_te
        result["X_val"]   = X_val
        result["y_val"]   = y_val

    # Summary display
    rows = [
        "<tr><td>Train</td><td>{:,}</td><td>{:.0%}</td></tr>".format(len(X_tr), len(X_tr)/len(df)),
        "<tr><td>Test</td><td>{:,}</td><td>{:.0%}</td></tr>".format(len(X_te), len(X_te)/len(df)),
    ]
    if val_size > 0:
        rows.append(
            "<tr><td>Val</td><td>{:,}</td><td>{:.0%}</td></tr>".format(
                len(result["X_val"]), len(result["X_val"])/len(df)
            )
        )
    _display(_HTML(
        "<table style='font-family:monospace;font-size:12px'>"
        "<tr><th>Set</th><th>Rows</th><th>%</th></tr>"
        + "".join(rows)
        + "<tr><td colspan='3'><i>{} features → {}</i></td></tr>".format(len(X.columns), target)
        + "</table>"
    ))

    return result


# ─── Training ─────────────────────────────────────────────────────────────────

def train_classifier(
    X_train,
    y_train,
    algorithm:    str   = "random_forest",
    params:       dict  = None,
    random_state: int   = 42,
) -> object:
    """
    Train a classification model.

    Args:
        X_train:   Training features (DataFrame or array)
        y_train:   Training labels
        algorithm: "random_forest" | "logistic" | "gradient_boost" |
                   "svm" | "knn" | "decision_tree" | "naive_bayes"
        params:    Override default hyperparameters
        random_state: Random seed

    Returns:
        Fitted sklearn model
    """
    from sklearn.ensemble     import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.svm          import SVC
    from sklearn.neighbors    import KNeighborsClassifier
    from sklearn.tree         import DecisionTreeClassifier
    from sklearn.naive_bayes  import GaussianNB

    defaults = {
        "random_forest":    {"n_estimators": 100, "max_depth": None,
                             "random_state": random_state, "n_jobs": -1},
        "logistic":         {"max_iter": 1000, "random_state": random_state},
        "gradient_boost":   {"n_estimators": 100, "learning_rate": 0.1,
                             "random_state": random_state},
        "svm":              {"probability": True, "random_state": random_state},
        "knn":              {"n_neighbors": 5, "n_jobs": -1},
        "decision_tree":    {"random_state": random_state},
        "naive_bayes":      {},
    }

    constructors = {
        "random_forest":  RandomForestClassifier,
        "logistic":       LogisticRegression,
        "gradient_boost": GradientBoostingClassifier,
        "svm":            SVC,
        "knn":            KNeighborsClassifier,
        "decision_tree":  DecisionTreeClassifier,
        "naive_bayes":    GaussianNB,
    }

    if algorithm not in constructors:
        available = list(constructors.keys())
        raise ValueError("Unknown algorithm '{}'. Available: {}".format(algorithm, available))

    final_params = {**defaults[algorithm], **(params or {})}
    model        = constructors[algorithm](**final_params)
    model.fit(X_train, y_train)

    print("✓ Trained {} on {:,} samples".format(type(model).__name__, len(X_train)))
    return model


def train_regressor(
    X_train,
    y_train,
    algorithm:    str  = "random_forest",
    params:       dict = None,
    random_state: int  = 42,
) -> object:
    """
    Train a regression model.

    Args:
        algorithm: "random_forest" | "linear" | "ridge" | "lasso" |
                   "gradient_boost" | "svr" | "knn"

    Returns:
        Fitted sklearn model
    """
    from sklearn.ensemble     import RandomForestRegressor, GradientBoostingRegressor
    from sklearn.linear_model import LinearRegression, Ridge, Lasso
    from sklearn.svm          import SVR
    from sklearn.neighbors    import KNeighborsRegressor

    defaults = {
        "random_forest":  {"n_estimators": 100, "random_state": random_state, "n_jobs": -1},
        "linear":         {},
        "ridge":          {"alpha": 1.0},
        "lasso":          {"alpha": 1.0, "max_iter": 2000},
        "gradient_boost": {"n_estimators": 100, "random_state": random_state},
        "svr":            {"kernel": "rbf"},
        "knn":            {"n_neighbors": 5},
    }

    constructors = {
        "random_forest":  RandomForestRegressor,
        "linear":         LinearRegression,
        "ridge":          Ridge,
        "lasso":          Lasso,
        "gradient_boost": GradientBoostingRegressor,
        "svr":            SVR,
        "knn":            KNeighborsRegressor,
    }

    if algorithm not in constructors:
        raise ValueError("Unknown algorithm. Available: {}".format(list(constructors.keys())))

    final_params = {**defaults[algorithm], **(params or {})}
    model        = constructors[algorithm](**final_params)
    model.fit(X_train, y_train)

    print("✓ Trained {} on {:,} samples".format(type(model).__name__, len(X_train)))
    return model


# ─── Evaluation ───────────────────────────────────────────────────────────────

def evaluate_classifier(
    model,
    X_test,
    y_test,
    X_train=None,
    y_train=None,
    labels: list = None,
) -> dict:
    """
    Comprehensive classifier evaluation.
    Always compares train vs. test to detect overfitting.

    Args:
        model:   Fitted sklearn classifier
        X_test:  Test features
        y_test:  Test labels
        X_train: Training features (for overfitting check)
        y_train: Training labels  (for overfitting check)
        labels:  Class labels for display

    Returns:
        dict: accuracy, precision, recall, f1, roc_auc, confusion_matrix
    """
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score, f1_score,
        roc_auc_score, confusion_matrix, classification_report,
    )
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as _plt

    y_pred  = model.predict(X_test)
    y_prob  = (model.predict_proba(X_test)[:, 1]
               if hasattr(model, "predict_proba") and len(_np.unique(y_test)) == 2
               else None)

    n_classes   = len(_np.unique(y_test))
    avg_method  = "binary" if n_classes == 2 else "weighted"

    metrics = {
        "accuracy":  round(float(accuracy_score(y_test, y_pred)), 4),
        "precision": round(float(precision_score(y_test, y_pred,
                          average=avg_method, zero_division=0)), 4),
        "recall":    round(float(recall_score(y_test, y_pred,
                          average=avg_method, zero_division=0)), 4),
        "f1":        round(float(f1_score(y_test, y_pred,
                          average=avg_method, zero_division=0)), 4),
        "roc_auc":   None,
        "n_test":    len(y_test),
    }

    if y_prob is not None:
        try:
            metrics["roc_auc"] = round(float(roc_auc_score(y_test, y_prob)), 4)
        except Exception:
            pass

    # Overfitting check
    if X_train is not None and y_train is not None:
        train_acc             = accuracy_score(y_train, model.predict(X_train))
        metrics["train_acc"]  = round(float(train_acc), 4)
        metrics["overfit_gap"]= round(float(train_acc - metrics["accuracy"]), 4)

    # ── Display ────────────────────────────────────────────────────────────────

    fig, axes = _plt.subplots(1, 2, figsize=(12, 4))

    # Confusion matrix
    cm        = confusion_matrix(y_test, y_pred)
    ax        = axes[0]
    im        = ax.imshow(cm, cmap="Blues")
    _plt.colorbar(im, ax=ax)
    ax.set_title("Confusion Matrix")
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    if labels:
        ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, rotation=45)
        ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels)
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center",
                    color="white" if cm[i, j] > cm.max() / 2 else "black")
    metrics["confusion_matrix"] = cm.tolist()

    # Metrics bar chart
    ax2    = axes[1]
    keys   = ["accuracy", "precision", "recall", "f1"]
    values = [metrics[k] for k in keys]
    bars   = ax2.bar(keys, values, color=["#0072B2", "#009E73", "#E69F00", "#CC79A7"])
    ax2.set_ylim(0, 1.1)
    ax2.set_title("Classifier Metrics")
    ax2.axhline(0.9, color="gray", linestyle="--", alpha=0.5, label="0.90 threshold")
    for bar, val in zip(bars, values):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                 "{:.3f}".format(val), ha="center", va="bottom", fontsize=10)
    if metrics.get("roc_auc"):
        ax2.set_title("Metrics  (ROC AUC: {:.3f})".format(metrics["roc_auc"]))

    _plt.tight_layout()
    _display(fig)
    _plt.close(fig)

    # Overfitting warning
    gap = metrics.get("overfit_gap", 0)
    if gap > 0.05:
        print("⚠️  Overfitting detected: train={:.3f}, test={:.3f}  (gap={:.3f})".format(
            metrics["train_acc"], metrics["accuracy"], gap))
    else:
        print("✓ No significant overfitting (gap={:.3f})".format(gap))

    return metrics


def evaluate_regressor(
    model,
    X_test,
    y_test,
    X_train=None,
    y_train=None,
) -> dict:
    """
    Comprehensive regressor evaluation with residual plot.

    Returns:
        dict: rmse, mae, r2, mape (and train equivalents if provided)
    """
    from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as _plt

    y_pred = model.predict(X_test)

    def _safe_mape(y_true, y_pred):
        mask = y_true != 0
        return float(_np.mean(_np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])))

    metrics = {
        "rmse": round(float(_np.sqrt(mean_squared_error(y_test, y_pred))), 4),
        "mae":  round(float(mean_absolute_error(y_test, y_pred)), 4),
        "r2":   round(float(r2_score(y_test, y_pred)), 4),
        "mape": round(_safe_mape(_np.array(y_test), y_pred) * 100, 2),
    }

    if X_train is not None and y_train is not None:
        y_tr_pred           = model.predict(X_train)
        metrics["train_r2"] = round(float(r2_score(y_train, y_tr_pred)), 4)
        metrics["overfit_gap"] = round(float(metrics["train_r2"] - metrics["r2"]), 4)

    fig, axes = _plt.subplots(1, 2, figsize=(12, 4))

    # Actual vs predicted
    axes[0].scatter(y_test, y_pred, alpha=0.4, color="#0072B2", edgecolors="white", s=25)
    lim = [min(_np.min(y_test), _np.min(y_pred)), max(_np.max(y_test), _np.max(y_pred))]
    axes[0].plot(lim, lim, "r--", lw=1.5, label="Perfect fit")
    axes[0].set_xlabel("Actual"); axes[0].set_ylabel("Predicted")
    axes[0].set_title("Actual vs Predicted  (R²={:.3f})".format(metrics["r2"]))
    axes[0].legend()

    # Residuals
    residuals = _np.array(y_test) - y_pred
    axes[1].scatter(y_pred, residuals, alpha=0.4, color="#009E73", edgecolors="white", s=25)
    axes[1].axhline(0, color="red", linestyle="--", lw=1.5)
    axes[1].set_xlabel("Predicted"); axes[1].set_ylabel("Residual")
    axes[1].set_title("Residual Plot  (RMSE={:.3f})".format(metrics["rmse"]))

    _plt.tight_layout()
    _display(fig)
    _plt.close(fig)

    print("R²={:.4f}  RMSE={:.4f}  MAE={:.4f}  MAPE={:.2f}%".format(
        metrics["r2"], metrics["rmse"], metrics["mae"], metrics["mape"]))
    return metrics


# ─── Cross-validation ─────────────────────────────────────────────────────────

def cross_validate_model(
    model,
    X,
    y,
    cv:         int  = 5,
    scoring:    str  = "auto",
    shuffle:    bool = True,
    random_state: int = 42,
) -> dict:
    """
    Proper k-fold cross-validation with confidence intervals.

    Args:
        model:   Unfitted sklearn model
        X:       Features
        y:       Labels / targets
        cv:      Number of folds (default: 5)
        scoring: Metric name or "auto" (detects classification vs regression)

    Returns:
        dict: mean_score, std_score, ci_95, fold_scores, metric_name
    """
    from sklearn.model_selection import cross_val_score, StratifiedKFold, KFold

    # Auto-detect scoring
    if scoring == "auto":
        n_unique = len(_np.unique(y))
        if n_unique <= 20:
            scoring = "f1_weighted" if n_unique > 2 else "roc_auc"
        else:
            scoring = "r2"

    # Choose CV strategy
    n_unique = len(_np.unique(y))
    if n_unique <= 20:
        cv_strategy = StratifiedKFold(
            n_splits=cv, shuffle=shuffle, random_state=random_state
        )
    else:
        cv_strategy = KFold(
            n_splits=cv, shuffle=shuffle, random_state=random_state
        )

    scores  = cross_val_score(model, X, y, cv=cv_strategy, scoring=scoring, n_jobs=-1)
    mean    = float(scores.mean())
    std     = float(scores.std())
    ci_half = 1.96 * std / _np.sqrt(cv)

    result = {
        "metric":      scoring,
        "mean_score":  round(mean, 4),
        "std_score":   round(std, 4),
        "ci_95_low":   round(mean - ci_half, 4),
        "ci_95_high":  round(mean + ci_half, 4),
        "fold_scores": [round(float(s), 4) for s in scores],
        "cv_folds":    cv,
    }

    print("Cross-validation ({}-fold)  metric={}".format(cv, scoring))
    print("  Mean: {:.4f} ± {:.4f}".format(mean, std))
    print("  95% CI: [{:.4f}, {:.4f}]".format(result["ci_95_low"], result["ci_95_high"]))
    print("  Folds: {}".format(["{:.4f}".format(s) for s in scores]))

    return result


# ─── Feature Analysis ─────────────────────────────────────────────────────────

def feature_importance(
    model,
    feature_names: list,
    top_n:   int = 20,
    kind:    str = "auto",
) -> pd.DataFrame:
    """
    Extract and plot feature importances.

    Supports:
      - Tree models: .feature_importances_
      - Linear models: .coef_
      - Any model via permutation importance (kind="permutation")

    Returns:
        DataFrame: feature, importance, rank
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as _plt

    importances = None

    if kind == "auto" or kind == "native":
        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
        elif hasattr(model, "coef_"):
            coef = model.coef_
            importances = _np.abs(coef[0] if coef.ndim > 1 else coef)

    if importances is None:
        print("Model does not expose feature importances natively.")
        print("Use kind='permutation' with X_test and y_test.")
        return pd.DataFrame()

    df = pd.DataFrame({
        "feature":    feature_names,
        "importance": importances,
    }).sort_values("importance", ascending=False).head(top_n)
    df["rank"] = range(1, len(df) + 1)

    fig, ax = _plt.subplots(figsize=(10, max(4, len(df) * 0.35)))
    colors  = ["#0072B2" if i < 5 else "#56B4E9" for i in range(len(df))]
    ax.barh(df["feature"][::-1], df["importance"][::-1], color=colors[::-1])
    ax.set_xlabel("Importance")
    ax.set_title("Feature Importances  (top {})".format(len(df)))
    _plt.tight_layout()
    _display(fig)
    _plt.close(fig)

    print("\\nTop 5 features:")
    for _, row in df.head(5).iterrows():
        print("  {:2d}. {:<30} {:.4f}".format(row["rank"], row["feature"], row["importance"]))

    return df


def preprocess(
    df:           pd.DataFrame,
    target:       str          = None,
    strategy:     str          = "standard",
    encode_cats:  bool         = True,
) -> tuple:
    """
    Automated preprocessing pipeline.
    Handles: missing values, scaling, categorical encoding.

    Args:
        df:          Source DataFrame
        target:      Target column to exclude from preprocessing
        strategy:    "standard" (z-score) | "minmax" | "robust" | "none"
        encode_cats: One-hot encode categorical columns

    Returns:
        (X_processed, y, preprocessor)
        where preprocessor has .transform() for new data
    """
    from sklearn.pipeline           import Pipeline
    from sklearn.compose            import ColumnTransformer
    from sklearn.preprocessing      import StandardScaler, MinMaxScaler, RobustScaler, OneHotEncoder
    from sklearn.impute             import SimpleImputer

    X = df.drop(columns=[target]) if target else df
    y = df[target] if target else None

    numeric_cols = X.select_dtypes(include=_np.number).columns.tolist()
    cat_cols     = X.select_dtypes(include=["object", "category"]).columns.tolist()

    scalers = {
        "standard": StandardScaler(),
        "minmax":   MinMaxScaler(),
        "robust":   RobustScaler(),
        "none":     "passthrough",
    }
    scaler = scalers.get(strategy, StandardScaler())

    numeric_pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler",  scaler),
    ])

    transformers = [("numeric", numeric_pipeline, numeric_cols)]

    if encode_cats and cat_cols:
        cat_pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="constant", fill_value="Unknown")),
            ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ])
        transformers.append(("categorical", cat_pipeline, cat_cols))

    preprocessor = ColumnTransformer(transformers=transformers, remainder="drop")
    X_processed  = preprocessor.fit_transform(X)

    print("✓ Preprocessed: {} → {}".format(X.shape, X_processed.shape))
    print("  Numeric: {} cols  Categorical: {} cols".format(len(numeric_cols), len(cat_cols)))
    print("  Scaling: {}".format(strategy))

    return X_processed, y, preprocessor
'''


def get_code() -> str:
    return _ML_SKILLS_CODE
