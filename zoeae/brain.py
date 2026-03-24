"""
Brain — The reasoning organ of a Zoeae organism.

Accepts any LLM backend (Ollama local, Anthropic API, raw HTTP).
Reasoning style adapts to the organism's developmental stage:
  - High bleed (early): divergent, associative, creative
  - Low bleed (late): convergent, precise, analytical

The brain is an organ, not the organism. It is constrained by the
exoskeleton, shaped by the antenna, and develops with molt.

    eco = Ecosystem("taos")
    m = Maker.hatch(eco)
    m.brain = Brain(backend=OllamaBackend("deepseek-r1:32b"))
    sight = m.see("pressure vessel for hydrogen")
    # Brain now interprets the sight and generates design proposals

AnnulusLabs LLC — Taos, NM
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from .antenna import Detection
from .exoskeleton import Exoskeleton


# ── REASONING MODES (bleed-dependent) ──

@dataclass
class ReasoningMode:
    """How the brain thinks, derived from developmental stage."""
    temperature: float = 0.7
    system_prompt: str = ""
    max_tokens: int = 2048
    style: str = "balanced"  # divergent | balanced | convergent | laser

    @staticmethod
    def from_bleed(bleed: float) -> "ReasoningMode":
        """Map antenna bleed width to reasoning parameters.
        High bleed = divergent/creative. Low bleed = convergent/precise."""
        if bleed > 0.7:
            return ReasoningMode(
                temperature=0.95,
                style="divergent",
                system_prompt=(
                    "Think broadly. Make unexpected connections across domains. "
                    "Quantity of ideas over precision. Challenge assumptions. "
                    "Consider approaches from unrelated fields."
                ),
                max_tokens=4096,
            )
        elif bleed > 0.4:
            return ReasoningMode(
                temperature=0.7,
                style="balanced",
                system_prompt=(
                    "Balance creativity with rigor. Propose multiple approaches "
                    "but evaluate feasibility. Ground ideas in physics and "
                    "engineering constraints."
                ),
                max_tokens=2048,
            )
        elif bleed > 0.15:
            return ReasoningMode(
                temperature=0.4,
                style="convergent",
                system_prompt=(
                    "Be precise and analytical. Focus on the most promising "
                    "approach. Identify specific failure modes. Provide "
                    "actionable engineering specifications."
                ),
                max_tokens=2048,
            )
        else:
            return ReasoningMode(
                temperature=0.15,
                style="laser",
                system_prompt=(
                    "Maximum precision. One answer, fully specified. "
                    "Include tolerances, materials, dimensions. "
                    "If something won't work, say so immediately."
                ),
                max_tokens=1024,
            )


# ── BACKENDS ──

class Backend(ABC):
    """Abstract LLM backend. Implement for each provider."""

    @abstractmethod
    def generate(self, prompt: str, system: str = "",
                 temperature: float = 0.7, max_tokens: int = 2048) -> str:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...


class OllamaBackend(Backend):
    """Local Ollama backend. No cloud, no API keys."""

    def __init__(self, model: str = "deepseek-r1:32b",
                 url: str = "http://127.0.0.1:11434"):
        self.model = model
        self.url = url.rstrip("/")

    def generate(self, prompt: str, system: str = "",
                 temperature: float = 0.7, max_tokens: int = 2048) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())
        return result.get("response", "")

    @property
    def name(self) -> str:
        return f"ollama/{self.model}"


class AnthropicBackend(Backend):
    """Anthropic Claude API backend."""

    def __init__(self, model: str = "claude-sonnet-4-6",
                 api_key: str = ""):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    def generate(self, prompt: str, system: str = "",
                 temperature: float = 0.7, max_tokens: int = 2048) -> str:
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("pip install anthropic")

        client = anthropic.Anthropic(api_key=self.api_key)
        msg = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=min(temperature, 1.0),
            system=system or "You are a precise engineering assistant.",
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    @property
    def name(self) -> str:
        return f"anthropic/{self.model}"


class HTTPBackend(Backend):
    """Raw HTTP backend for any OpenAI-compatible API."""

    def __init__(self, url: str, model: str = "default",
                 api_key: str = "", headers: Optional[dict] = None):
        self.url = url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.extra_headers = headers or {}

    def generate(self, prompt: str, system: str = "",
                 temperature: float = 0.7, max_tokens: int = 2048) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        headers.update(self.extra_headers)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(
            f"{self.url}/v1/chat/completions",
            data=data,
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())
        return result["choices"][0]["message"]["content"]

    @property
    def name(self) -> str:
        return f"http/{self.model}"


# ── THOUGHT ──

@dataclass
class Thought:
    """The output of the brain processing a perception."""
    content: str
    mode: ReasoningMode
    backend: str
    detection: Optional[Detection] = None
    duration_s: float = 0.0
    bleed: float = 0.0
    safe: bool = True
    safety_note: str = ""

    @property
    def summary(self) -> str:
        lines = self.content.strip().split("\n")
        return lines[0][:120] if lines else ""


# ── BRAIN ──

class Brain:
    """The reasoning organ. Plugs into any LLM backend.
    Adapts reasoning style to the organism's developmental stage.
    Constrained by the exoskeleton — no unsafe outputs pass through.
    """

    def __init__(self, backend: Optional[Backend] = None,
                 exoskeleton: Optional[Exoskeleton] = None):
        self.backend = backend
        self.exo = exoskeleton or Exoskeleton()
        self._thoughts: list[Thought] = []

    def think(self, prompt: str, bleed: float = 0.5,
              detection: Optional[Detection] = None,
              context: str = "") -> Thought:
        """Generate a thought. Reasoning style adapts to bleed width."""
        if not self.backend:
            return Thought(
                content="[no backend configured]",
                mode=ReasoningMode(),
                backend="none",
                bleed=bleed,
            )

        mode = ReasoningMode.from_bleed(bleed)

        # Build the full prompt with context
        full_prompt = self._build_prompt(prompt, detection, context, mode)

        # Guard input through exoskeleton
        inspection = self.exo.inspect(full_prompt)
        if inspection.compromised:
            return Thought(
                content="[blocked by exoskeleton]",
                mode=mode,
                backend=self.backend.name,
                detection=detection,
                bleed=bleed,
                safe=False,
                safety_note=f"Input blocked: {inspection.threats}",
            )

        # Generate
        t0 = time.time()
        try:
            raw = self.backend.generate(
                prompt=full_prompt,
                system=mode.system_prompt,
                temperature=mode.temperature,
                max_tokens=mode.max_tokens,
            )
        except Exception as e:
            return Thought(
                content=f"[error: {e}]",
                mode=mode,
                backend=self.backend.name,
                detection=detection,
                bleed=bleed,
            )
        duration = time.time() - t0

        # Guard output through exoskeleton
        output_inspection = self.exo.inspect(raw)
        scrubbed = self.exo.scrub(raw)

        thought = Thought(
            content=scrubbed,
            mode=mode,
            backend=self.backend.name,
            detection=detection,
            duration_s=duration,
            bleed=bleed,
            safe=not output_inspection.compromised,
            safety_note=f"Output scrubbed" if scrubbed != raw else "",
        )

        self._thoughts.append(thought)
        return thought

    def interpret_sight(self, idea: str, sight: Any,
                        bleed: float = 0.5) -> Thought:
        """Interpret a Sight result and generate a design proposal."""
        context_parts = [f"Idea: {idea}"]

        if hasattr(sight, 'physics_check') and sight.physics_check:
            pc = sight.physics_check
            status = "PASS" if pc.get("survives") else "FAIL"
            context_parts.append(f"Physics: {status} ({pc.get('passed', 0)} passed, {pc.get('failed', 0)} failed)")
            if pc.get("details"):
                context_parts.append(f"  Failures: {', '.join(pc['details'])}")

        if hasattr(sight, 'expert_match') and sight.expert_match:
            e = sight.expert_match
            context_parts.append(f"Expert available: {e.get('domain', 'unknown')} ({e.get('years', '?')}yr)")

        if hasattr(sight, 'fab_options') and sight.fab_options:
            caps = set(f.get("capability", "") for f in sight.fab_options)
            context_parts.append(f"Fabrication: {len(sight.fab_options)} options ({', '.join(caps)})")

        if hasattr(sight, 'confidence'):
            context_parts.append(f"Confidence: {sight.confidence:.2f}")

        if hasattr(sight, 'go_no_go'):
            context_parts.append(f"Verdict: {sight.go_no_go}")

        context = "\n".join(context_parts)

        prompt = (
            f"Based on this perception analysis, generate a concrete design proposal "
            f"for: {idea}\n\n"
            f"Perception context:\n{context}\n\n"
            f"Include: key components, materials, critical dimensions, "
            f"potential failure modes, and next steps."
        )

        return self.think(
            prompt=prompt,
            bleed=bleed,
            detection=sight.detection if hasattr(sight, 'detection') else None,
            context=context,
        )

    def _build_prompt(self, prompt: str, detection: Optional[Detection],
                      context: str, mode: ReasoningMode) -> str:
        """Build the full prompt with perception data."""
        parts = []

        if context:
            parts.append(f"Context:\n{context}")

        if detection:
            channels = ", ".join(
                f"CH{i+1}={v:.3f}" for i, v in enumerate(detection.channel_activations)
            )
            parts.append(
                f"Antenna perception: dominant=CH{detection.dominant_channel+1}, "
                f"sharpness={detection.sharpness:.3f}, "
                f"asymmetry={detection.asymmetry:.3f}\n"
                f"Channels: [{channels}]"
            )

        parts.append(prompt)
        return "\n\n".join(parts)

    @property
    def thought_count(self) -> int:
        return len(self._thoughts)

    @property
    def last_thought(self) -> Optional[Thought]:
        return self._thoughts[-1] if self._thoughts else None

    @property
    def stats(self) -> dict:
        return {
            "backend": self.backend.name if self.backend else "none",
            "thoughts": len(self._thoughts),
            "avg_duration": (
                sum(t.duration_s for t in self._thoughts) / len(self._thoughts)
                if self._thoughts else 0
            ),
            "safety_blocks": sum(1 for t in self._thoughts if not t.safe),
        }
