class VisualGroundingDeviceError(RuntimeError):
    """Requested sidecar model device is unavailable or invalid."""


class VisualGroundingRuntimeParameterError(ValueError):
    """Requested sidecar runtime parameter is malformed or out of range."""
