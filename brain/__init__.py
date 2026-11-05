"""Cerebro NFL: motor de análisis y predicción."""
import warnings

warnings.filterwarnings("ignore", category=Warning, module="pandas")
warnings.filterwarnings("ignore", message=".*PerformanceWarning.*")
warnings.simplefilter("ignore", category=FutureWarning)
try:
    from pandas.errors import PerformanceWarning
    warnings.simplefilter("ignore", category=PerformanceWarning)
except Exception:  # noqa: BLE001
    pass
