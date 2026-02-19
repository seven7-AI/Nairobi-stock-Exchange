"""Domain-specific exceptions."""


class NSEAnalysisError(Exception):
    """Base exception for the nse-analysis package."""


class DatabaseConnectionError(NSEAnalysisError):
    """Raised when the database cannot be reached."""


class DataValidationError(NSEAnalysisError):
    """Raised when inbound data fails validation checks."""


class IndicatorCalculationError(NSEAnalysisError):
    """Raised when indicators cannot be computed safely."""


class ReportGenerationError(NSEAnalysisError):
    """Raised when report rendering fails."""
