# Exoskeleton Verification Gate

**Verification gate for all shipped code.**

---

## The 4-Line Atomic Prompt

Before shipping any function, module, or system:

```
1. WHAT does this code actually do? (not what I intended)
2. WHAT are the 3 most likely failure modes?
3. WHAT assumptions am I making that could be wrong?
4. WHAT would a hostile reviewer catch in 30 seconds?
```

Answer all four. If you cannot answer any one of them, do not ship.

---

## The 8 Reasoning Flaws

These are the failure modes that kill systems:

| # | Flaw | Symptom |
|---|------|---------|
| 1 | **Confirmation bias** | Only testing the happy path |
| 2 | **Anchoring** | First implementation becomes the only implementation |
| 3 | **Availability heuristic** | Solving the last bug, not the current bug |
| 4 | **Scope creep** | "While I'm in here..." |
| 5 | **Complexity worship** | Making it clever when simple works |
| 6 | **Authority bias** | It must be right, the docs say so |
| 7 | **Sunk cost** | Can't throw away code already written |
| 8 | **Optimism bias** | It will probably be fine |

---

## Prime Directive

**Ship the smallest thing that is actually correct.**

Not the most elegant. Not the most complete. The smallest correct thing.
Correctness is verified, not assumed.

---

## Application to Zoeae

All three runtimes (Rust, TypeScript, Python) are gated by this protocol:

- **Rust organs**: Each organ has a single responsibility. If you cannot state it in one sentence, the organ is too large.
- **TS plugin tools**: Every tool registered via `api.registerTool()` must have a documented failure mode in its description.
- **Python organs**: Every organ method that calls external state (Blood, Nerve, Genome) must handle the case where that state is absent or corrupted.

The `ExoSkeleton.inspect()` wrapper in both Python and Rust enforces this at runtime. The Exoskeleton gate enforces it at design time.

---

## Verification Checklist

```
[ ] WHAT does it do — stated in one sentence
[ ] 3 failure modes — named specifically, not generically
[ ] Assumptions — listed and each one marked as verified or accepted risk
[ ] Hostile reviewer test — conducted, findings addressed
[ ] No reasoning flaws 1–8 present
[ ] Smallest correct thing — not largest possible thing
```

---

*AnnulusLabs LLC — Taos, NM*
*"The circle must remain broken to vibrate"*
