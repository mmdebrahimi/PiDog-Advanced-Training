# Crawl-gait RL: negative result, scoped (2026-10-31)

## What was tried (both arms MEASURED, 2M PPO steps each, DR on, CPU)

| arm | base gait | residual | eval_mvp (5 eps, DR off) | outcome |
|---|---|---|---|---|
| v1 | crawl, trot-convention stride, S10/L30/1.0Hz | 12 deg | fwd **-102mm**, lat 1mm, 1000 steps | smooth BACKWARD walk — backward basin is the easy optimum |
| v2 | crawl, least-backward base from sweep (flipped stride S10/L20/1.0Hz, -10mm/5s scripted-only) | 18 deg | fwd **-16mm**, lat 12mm, 1000 steps | stands in rhythm; no forward thrust learned |

Supporting sweep: 72 scripted-only configs x both stride signs (S in 10-25, L in 20-40,
0.75-1.5Hz) — EVERY crawl base drifts backward, monotonically worse with amplitude and
cadence. The trot base shares the bias (-74mm standalone, per LAPTOP_FINDINGS_2026-07-09).

## Scope (what this kills, and only this)

Residual-PPO on a SCRIPTED one-leg-at-a-time crawl base, in THIS pidog.xml sim, at 1.0Hz,
2M steps, 12-18 deg authority, run18-lineage reward: does not produce forward locomotion.

NOT killed: crawl on the real robot (the stock SunFounder Walk gait is a crawl and walks
forward on hardware by design — rubber feet, real friction); trot policies (432-496mm,
MVP PASS); crawl via on-hardware tuning/BO (Stage 1/2 of the staged plan, unaffected).

## Root-cause hypothesis (unfalsified — labeled, not established)

The sim's foot-ground contact makes slow, quasi-static gaits slip backward: backward drift
scales with commanded stride through BOTH stride directions, which points at foot-slip
during lift/plant rather than stride geometry. The 2Hz trot gives the policy momentum
dynamics to exploit (it escaped the same bias); the quasi-static 1Hz crawl offers only
friction, which the sim under-models. Falsifying/fixing this means contact-model work
(friction coefficients, foot geometry against real measurements) — out of scope here.

## Revival condition

Revisit crawl-RL only if BOTH: (a) the hardware brownout step test rules the trot out
(ceiling < 8 simultaneous servos even with --slew-cap/--stagger-ms), AND (b) Stage-1
hardware work produces a measured forward-walking crawl trajectory to use as the base
(replacing the scripted base with a hardware-validated one removes the sim-slip problem
at its root — the residual then shapes a base that is forward by construction).

## Artifacts

pidog_policy_crawl.zip / pidog_policy_crawl_v2.zip (repo root, untracked checkpoints kept
locally on the laptop) — both fail the gate; NOT staged to deploy/, deliberately. The env
support (PiDogEnv base_gait="crawl") is committed and tested — it is the vehicle for the
revival condition, not dead weight.
