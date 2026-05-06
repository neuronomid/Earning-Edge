__all__ = ["PipelineOrchestrator", "get_pipeline_orchestrator"]


def __getattr__(name: str):
    if name in __all__:
        from app.pipeline.orchestrator import (
            PipelineOrchestrator,
            get_pipeline_orchestrator,
        )

        exported = {
            "PipelineOrchestrator": PipelineOrchestrator,
            "get_pipeline_orchestrator": get_pipeline_orchestrator,
        }
        return exported[name]
    raise AttributeError(name)
