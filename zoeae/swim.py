"""
Swim — Goal pursuit / planning organ. Pleopods.

Active movement toward objectives. The organism pursues goals
autonomously. Plans adapt to bleed: high bleed = broad exploration
steps, low bleed = precise execution steps. Plans can be revised
mid-swim when new perception data changes the picture.

    brain = Brain(backend=OllamaBackend("deepseek-r1:32b"))
    hands = Hands(exo=exoskeleton)
    swim  = Swim(hands=hands)
    plan  = swim.toward("analyze server logs for anomalies", brain)
    while plan.status == "swimming":
        result = swim.stroke()
        print(result.summary)

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional

from .brain import Brain, Thought
from .hands import Hands, ActionResult


# ── STATUS ENUMS ──

class PlanStatus(Enum):
    PLANNING  = auto()
    SWIMMING  = auto()
    DRIFTING  = auto()
    ARRIVED   = auto()
    FAILED    = auto()

class StepStatus(Enum):
    PENDING   = auto()
    ACTIVE    = auto()
    DONE      = auto()
    SKIPPED   = auto()
    FAILED    = auto()

class StepAction(Enum):
    SHELL     = auto()  # execute a command via hands.reach()
    THINK     = auto()  # reason about something via brain.think()
    PERCEIVE  = auto()  # gather information (read file, fetch URL)
    VALIDATE  = auto()  # check a result against expectations


# ── DATACLASSES ──

@dataclass
class Step:
    """A single step in a plan."""
    description: str
    action: StepAction = StepAction.THINK
    command: str = ""        # for SHELL actions
    query: str = ""          # for THINK/PERCEIVE/VALIDATE actions
    status: StepStatus = StepStatus.PENDING
    result: str = ""
    duration_s: float = 0.0
    error: str = ""

    @property
    def summary(self) -> str:
        status_tag = self.status.name
        preview = self.result[:120] if self.result else self.description[:120]
        return f"[{status_tag}] {self.action.name}: {preview}"


@dataclass
class StepResult:
    """The outcome of executing a single step."""
    step_index: int
    step: Step
    success: bool
    output: str
    duration_s: float = 0.0

    @property
    def summary(self) -> str:
        tag = "OK" if self.success else "FAIL"
        preview = self.output[:120] if self.output else self.step.description[:120]
        return f"[{tag}] step {self.step_index}: {preview}"


@dataclass
class Plan:
    """A decomposed goal with ordered steps."""
    goal: str
    steps: list[Step] = field(default_factory=list)
    current_step_idx: int = 0
    status: str = "planning"  # planning | swimming | drifting | arrived | failed
    bleed: float = 0.5
    created_at: float = field(default_factory=time.time)
    revised_count: int = 0
    _results: list[StepResult] = field(default_factory=list)

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        done = sum(1 for s in self.steps
                   if s.status in (StepStatus.DONE, StepStatus.SKIPPED))
        return done / len(self.steps)

    @property
    def current_step(self) -> Optional[Step]:
        if 0 <= self.current_step_idx < len(self.steps):
            return self.steps[self.current_step_idx]
        return None

    @property
    def remaining(self) -> int:
        return sum(1 for s in self.steps
                   if s.status == StepStatus.PENDING)

    @property
    def results(self) -> list[StepResult]:
        return list(self._results)

    @property
    def summary(self) -> str:
        total = len(self.steps)
        done = sum(1 for s in self.steps if s.status == StepStatus.DONE)
        failed = sum(1 for s in self.steps if s.status == StepStatus.FAILED)
        return (
            f"Plan: {self.goal[:80]}\n"
            f"Status: {self.status} | Steps: {done}/{total} done, "
            f"{failed} failed | Bleed: {self.bleed:.2f} | "
            f"Revisions: {self.revised_count}"
        )


# ── SWIM ──

class Swim:
    """The goal-pursuit organ. Pleopods.

    Decomposes goals into steps using the brain. Executes steps
    using the hands. Adapts plan granularity to bleed width:
    high bleed produces broad exploratory steps, low bleed
    produces precise execution steps. Plans can be revised
    mid-swim when new information changes the picture.
    """

    def __init__(self, hands: Optional[Hands] = None) -> None:
        self.hands = hands or Hands()
        self._plan: Optional[Plan] = None
        self._plans: list[Plan] = []

    # ── goal decomposition ──

    def toward(self, goal: str, brain: Brain,
               bleed: float = 0.5, max_steps: int = 10) -> Plan:
        """Decompose a goal into steps using the brain.

        High bleed = broad exploration steps (divergent).
        Low bleed  = precise execution steps (convergent).
        """
        plan = Plan(goal=goal, bleed=bleed, status="planning")

        # Build the decomposition prompt based on bleed
        prompt = self._decomposition_prompt(goal, bleed, max_steps)
        thought = brain.think(prompt, bleed=bleed)

        if not thought.safe:
            plan.status = "failed"
            plan.steps = [Step(
                description=f"Planning blocked: {thought.safety_note}",
                status=StepStatus.FAILED,
                error=thought.safety_note,
            )]
            self._plan = plan
            self._plans.append(plan)
            return plan

        # Parse steps from the brain's response
        steps = self._parse_steps(thought.content, bleed)

        if not steps:
            # Fallback: single thinking step
            steps = [Step(
                description=f"Analyze: {goal}",
                action=StepAction.THINK,
                query=goal,
            )]

        plan.steps = steps
        plan.status = "swimming"
        self._plan = plan
        self._plans.append(plan)
        return plan

    # ── step execution ──

    def stroke(self, brain: Optional[Brain] = None,
               bleed: Optional[float] = None) -> StepResult:
        """Execute the next step in the current plan.

        Returns the result. Advances the plan state.
        If brain is provided, THINK and VALIDATE steps use it.
        """
        if self._plan is None:
            raise RuntimeError("No plan — call toward() first")

        plan = self._plan
        if plan.status not in ("swimming",):
            raise RuntimeError(f"Cannot stroke: plan status is '{plan.status}'")

        step = plan.current_step
        if step is None:
            plan.status = "arrived"
            return StepResult(
                step_index=plan.current_step_idx,
                step=Step(description="No more steps"),
                success=True,
                output="Plan complete",
            )

        step.status = StepStatus.ACTIVE
        effective_bleed = bleed if bleed is not None else plan.bleed
        t0 = time.time()

        try:
            output = self._execute_step(step, brain, effective_bleed)
            step.result = output
            step.status = StepStatus.DONE
            success = True
        except Exception as e:
            step.error = str(e)
            step.result = f"[error] {e}"
            step.status = StepStatus.FAILED
            output = step.result
            success = False

        step.duration_s = time.time() - t0

        result = StepResult(
            step_index=plan.current_step_idx,
            step=step,
            success=success,
            output=output,
            duration_s=step.duration_s,
        )
        plan._results.append(result)

        # Advance
        plan.current_step_idx += 1
        if plan.current_step_idx >= len(plan.steps):
            # Check if any steps failed
            failed = any(s.status == StepStatus.FAILED for s in plan.steps)
            plan.status = "failed" if failed else "arrived"

        return result

    # ── drift ──

    def drift(self) -> None:
        """Pause pursuit. Let the ocean carry.

        The plan remains in memory but execution stops.
        Can be resumed by calling stroke() after setting
        status back to swimming.
        """
        if self._plan is not None:
            self._plan.status = "drifting"

    def resume(self) -> Optional[Plan]:
        """Resume a drifting plan."""
        if self._plan is not None and self._plan.status == "drifting":
            self._plan.status = "swimming"
        return self._plan

    # ── plan revision ──

    def revise(self, brain: Brain, new_context: str = "",
               bleed: Optional[float] = None) -> Plan:
        """Revise the current plan based on new information.

        Completed steps are preserved. Remaining steps are
        re-planned using the brain with accumulated context.
        """
        if self._plan is None:
            raise RuntimeError("No plan to revise — call toward() first")

        plan = self._plan
        effective_bleed = bleed if bleed is not None else plan.bleed

        # Gather completed results as context
        completed_context = self._build_revision_context(plan, new_context)

        prompt = (
            f"Revise this plan based on new information.\n\n"
            f"Original goal: {plan.goal}\n\n"
            f"Completed so far:\n{completed_context}\n\n"
            f"New information: {new_context}\n\n"
            f"Generate revised remaining steps. "
            f"The goal has not changed. Adjust approach based on what "
            f"we've learned."
        )

        thought = brain.think(prompt, bleed=effective_bleed)

        if thought.safe:
            new_steps = self._parse_steps(thought.content, effective_bleed)
            if new_steps:
                # Keep completed steps, replace remaining
                completed = [s for s in plan.steps
                             if s.status in (StepStatus.DONE, StepStatus.SKIPPED)]
                plan.steps = completed + new_steps
                plan.current_step_idx = len(completed)
                plan.revised_count += 1
                plan.status = "swimming"

        return plan

    # ── internal ──

    def _decomposition_prompt(self, goal: str, bleed: float,
                              max_steps: int) -> str:
        """Build the goal decomposition prompt. Adapts to bleed."""
        if bleed > 0.7:
            style = (
                "Break this into broad exploration steps. Each step should "
                "investigate a different angle or gather different information. "
                "Prefer perceive and think actions. Cast a wide net."
            )
        elif bleed > 0.4:
            style = (
                "Break this into balanced steps mixing investigation and "
                "execution. Include validation steps to check progress."
            )
        elif bleed > 0.15:
            style = (
                "Break this into precise, actionable steps. Each step should "
                "have a clear deliverable. Prefer shell and validate actions."
            )
        else:
            style = (
                "Break this into the minimum number of exact steps. "
                "Each step must be a concrete command or verification. "
                "No exploration — direct path to the goal."
            )

        return (
            f"Goal: {goal}\n\n"
            f"{style}\n\n"
            f"Maximum {max_steps} steps.\n\n"
            f"For each step, output one line in this exact format:\n"
            f"  ACTION: description | command_or_query\n\n"
            f"ACTION must be one of: SHELL, THINK, PERCEIVE, VALIDATE\n"
            f"For SHELL steps, the command_or_query is the shell command.\n"
            f"For THINK steps, it is the question to reason about.\n"
            f"For PERCEIVE steps, it is the file path or URL to read.\n"
            f"For VALIDATE steps, it is the condition to check.\n\n"
            f"Output ONLY the steps, one per line. No preamble."
        )

    def _parse_steps(self, content: str, bleed: float) -> list[Step]:
        """Parse brain output into Step objects."""
        steps = []
        action_map = {
            "SHELL": StepAction.SHELL,
            "THINK": StepAction.THINK,
            "PERCEIVE": StepAction.PERCEIVE,
            "VALIDATE": StepAction.VALIDATE,
        }

        for line in content.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Try to parse "ACTION: description | command"
            parsed = False
            for action_name, action_enum in action_map.items():
                if line.upper().startswith(action_name + ":"):
                    rest = line[len(action_name) + 1:].strip()
                    parts = rest.split("|", 1)
                    description = parts[0].strip()
                    cmd_or_query = parts[1].strip() if len(parts) > 1 else ""

                    step = Step(
                        description=description,
                        action=action_enum,
                        command=cmd_or_query if action_enum == StepAction.SHELL else "",
                        query=cmd_or_query if action_enum != StepAction.SHELL else "",
                    )
                    steps.append(step)
                    parsed = True
                    break

            # Fallback: treat unparseable lines as THINK steps
            if not parsed and len(line) > 5:
                # Strip numbering like "1." or "- "
                clean = line.lstrip("0123456789.-) ").strip()
                if clean:
                    steps.append(Step(
                        description=clean,
                        action=StepAction.THINK,
                        query=clean,
                    ))

        return steps

    def _execute_step(self, step: Step, brain: Optional[Brain],
                      bleed: float) -> str:
        """Execute a single step. Returns the output string."""
        if step.action == StepAction.SHELL:
            if not step.command:
                return "[no command specified]"
            result = self.hands.reach(step.command)
            if not result.safe:
                raise PermissionError(
                    f"Command blocked: {result.blocked_reason}"
                )
            if result.exit_code != 0 and result.stderr:
                return f"[exit {result.exit_code}] {result.stderr}"
            return result.stdout

        elif step.action == StepAction.THINK:
            if brain is None:
                return f"[no brain] {step.query or step.description}"
            thought = brain.think(step.query or step.description, bleed=bleed)
            if not thought.safe:
                return f"[blocked] {thought.safety_note}"
            return thought.content

        elif step.action == StepAction.PERCEIVE:
            target = step.query or step.command
            if not target:
                return "[no target to perceive]"
            # URL or file?
            if target.startswith("http://") or target.startswith("https://"):
                return self.hands.fetch(target)
            else:
                return self.hands.grasp(target)

        elif step.action == StepAction.VALIDATE:
            # Validation uses the brain to check a condition
            condition = step.query or step.description
            if brain is None:
                return f"[no brain — cannot validate] {condition}"
            # Build context from previous results
            context_parts = []
            if self._plan:
                for prev in self._plan._results[-5:]:
                    context_parts.append(
                        f"Step {prev.step_index}: {prev.step.description}\n"
                        f"  Result: {prev.output[:200]}"
                    )
            context = "\n".join(context_parts)

            prompt = (
                f"Validate this condition based on the work done so far:\n\n"
                f"Condition: {condition}\n\n"
                f"Previous results:\n{context}\n\n"
                f"Answer: PASS or FAIL, with a brief explanation."
            )
            thought = brain.think(prompt, bleed=min(bleed, 0.3))
            return thought.content

        return f"[unknown action: {step.action}]"

    def _build_revision_context(self, plan: Plan,
                                new_context: str) -> str:
        """Build context string from completed steps for revision."""
        parts = []
        for i, step in enumerate(plan.steps):
            if step.status in (StepStatus.DONE, StepStatus.SKIPPED):
                result_preview = step.result[:200] if step.result else "(no output)"
                parts.append(
                    f"  {i+1}. [{step.status.name}] {step.description}\n"
                    f"     Result: {result_preview}"
                )
            elif step.status == StepStatus.FAILED:
                parts.append(
                    f"  {i+1}. [FAILED] {step.description}\n"
                    f"     Error: {step.error}"
                )
        if new_context:
            parts.append(f"\nNew context: {new_context}")
        return "\n".join(parts) if parts else "(no steps completed yet)"

    # ── introspection ──

    @property
    def plan(self) -> Optional[Plan]:
        return self._plan

    @property
    def is_swimming(self) -> bool:
        return self._plan is not None and self._plan.status == "swimming"

    @property
    def is_drifting(self) -> bool:
        return self._plan is not None and self._plan.status == "drifting"

    @property
    def has_arrived(self) -> bool:
        return self._plan is not None and self._plan.status == "arrived"

    @property
    def stats(self) -> dict:
        total_steps = sum(len(p.steps) for p in self._plans)
        completed = sum(
            sum(1 for s in p.steps if s.status == StepStatus.DONE)
            for p in self._plans
        )
        failed = sum(
            sum(1 for s in p.steps if s.status == StepStatus.FAILED)
            for p in self._plans
        )
        return {
            "plans": len(self._plans),
            "active_plan": self._plan.goal[:80] if self._plan else None,
            "active_status": self._plan.status if self._plan else None,
            "total_steps": total_steps,
            "completed": completed,
            "failed": failed,
            "total_revisions": sum(p.revised_count for p in self._plans),
        }
