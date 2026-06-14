from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ModelRoute:
    stage: str
    primary: str
    fallbacks: tuple[str, ...]
    env_var: str
    heavy: bool
    gate: str


ROUTES: dict[str, ModelRoute] = {
    "consolidation": ModelRoute(
        stage="consolidation",
        primary="ollama:gemma3:4b",
        fallbacks=("api:moonshot:default", "off"),
        env_var="ARI_OS_CONSOLIDATION_LLM",
        heavy=True,
        gate="consolidation smoke plus summary sanity check",
    ),
    "kg_extraction": ModelRoute(
        stage="kg_extraction",
        primary="ollama:gemma3:4b",
        fallbacks=("api:moonshot:default", "off"),
        env_var="ARI_OS_KG_LLM",
        heavy=True,
        gate="KG extraction smoke plus parser sanity check",
    ),
}


def route_for_stage(stage: str) -> ModelRoute:
    try:
        return ROUTES[stage]
    except KeyError as exc:
        valid = ", ".join(sorted(ROUTES))
        raise ValueError(
            f"Unknown cortex model stage {stage!r}; valid stages: {valid}"
        ) from exc


def model_for_stage(stage: str) -> str:
    route = route_for_stage(stage)
    override = os.environ.get(route.env_var, "").strip()
    return override or route.primary
