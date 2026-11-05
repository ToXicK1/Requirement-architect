"""Stage 9: UI/UX. Refuses to keep invented screens for API-only projects."""

from __future__ import annotations

from requirements_architect.agent.stages.common import (
    StageContext,
    base_untrusted,
    render_architecture,
    render_data_api,
    run_stage,
)
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.schemas.dataapi import DataApiSpec
from requirements_architect.schemas.requirements import RequirementsSpec, Severity, SpecIssue
from requirements_architect.schemas.ux import Flow, RawUx, Screen, UiState, UxSpec

_REQUIRED_STATES = (UiState.LOADING, UiState.ERROR, UiState.EMPTY)


def _issue(
    issues: list[SpecIssue], code: str, msg: str, ref: str | None = None, *, error: bool = False
) -> None:
    issues.append(
        SpecIssue(
            code=code, severity=Severity.ERROR if error else Severity.WARNING, message=msg, ref=ref
        )
    )


def build_ux(raw: RawUx, reqs: RequirementsSpec, api: DataApiSpec | None) -> UxSpec:
    issues: list[SpecIssue] = []
    valid_reqs = {f.id for f in reqs.functional} | {n.id for n in reqs.nonfunctional}
    valid_eps = {e.id for e in api.endpoints} if api else set()

    def req_ids(ids: list[str], ref: str) -> list[str]:
        out = [r for r in dict.fromkeys(ids) if r in valid_reqs]
        for r in dict.fromkeys(ids):
            if r not in valid_reqs:
                _issue(issues, "UNKNOWN_REQUIREMENT", f"{ref} cites unknown requirement {r}", ref)
        return out

    if not raw.has_ui:
        if raw.screens or raw.navigation:
            _issue(
                issues,
                "SCREENS_FOR_NON_UI_PROJECT",
                "screens/navigation were supplied although has_ui is false; they were dropped",
            )
        if not raw.interface_note.strip():
            _issue(issues, "NO_INTERFACE_SPEC", "no UI and no interface description", error=True)
        flows = [
            Flow(
                id=f"FL-{i:03d}",
                name=f.name,
                actor=f.actor,
                steps=f.steps,
                requirement_ids=req_ids(f.requirement_ids, f"FL-{i:03d}"),
            )
            for i, f in enumerate(raw.flows, 1)
        ]
        return UxSpec(
            has_ui=False,
            interface_note=raw.interface_note,
            flows=flows,
            design_system=[],
            accessibility_requirements=raw.accessibility_requirements,
            issues=issues,
        )

    screens: list[Screen] = []
    for i, s in enumerate(raw.screens, 1):
        sid = f"SCR-{i:03d}"
        eps = [e for e in dict.fromkeys(s.endpoint_ids) if e in valid_eps]
        for e in dict.fromkeys(s.endpoint_ids):
            if e not in valid_eps:
                _issue(issues, "UNKNOWN_ENDPOINT", f"{sid} cites unknown endpoint {e}", sid)
        have = {st.state for st in s.states}
        for state in _REQUIRED_STATES:
            if state not in have:
                _issue(
                    issues,
                    "SCREEN_MISSING_STATE",
                    f"{sid} ({s.name}) defines no {state.value} state",
                    sid,
                )
        if not s.accessibility:
            _issue(
                issues,
                "SCREEN_NO_ACCESSIBILITY",
                f"{sid} ({s.name}) has no accessibility notes",
                sid,
            )
        screens.append(
            Screen(
                id=sid,
                name=s.name,
                purpose=s.purpose,
                inputs=s.inputs,
                outputs=s.outputs,
                states=s.states,
                responsive=s.responsive,
                accessibility=s.accessibility,
                requirement_ids=req_ids(s.requirement_ids, sid),
                endpoint_ids=eps,
            )
        )
    if not screens:
        _issue(issues, "NO_SCREENS", "has_ui is true but no screens were defined", error=True)
    if not raw.personas:
        _issue(issues, "NO_PERSONAS", "has_ui is true but no personas were defined")
    flows = [
        Flow(
            id=f"FL-{i:03d}",
            name=f.name,
            actor=f.actor,
            steps=f.steps,
            requirement_ids=req_ids(f.requirement_ids, f"FL-{i:03d}"),
        )
        for i, f in enumerate(raw.flows, 1)
    ]
    return UxSpec(
        has_ui=True,
        interface_note=raw.interface_note,
        personas=raw.personas,
        flows=flows,
        screens=screens,
        navigation=raw.navigation,
        design_system=raw.design_system,
        accessibility_requirements=raw.accessibility_requirements,
        issues=issues,
    )


async def generate_ux(gateway: LLMGateway, ctx: StageContext) -> UxSpec:
    api = ctx.extras.get("dataapi")
    untrusted = base_untrusted(ctx) | {
        "architecture": render_architecture(ctx.architecture),
        "dataapi": render_data_api(api),
    }
    raw = await run_stage(gateway, "ux", ctx, RawUx, untrusted)
    return build_ux(raw, ctx.requirements, api if isinstance(api, DataApiSpec) else None)
