# Decisions Log
<!-- Auto-maintained by /execute-plan and /retrospective. Do not edit manually. -->

## [plan_file: Person_Finding_Strategy_Plan.md] Executed 2026-04-05
**Mode:** sequential (4 steps) | **Result:** All 4 steps completed
**PRs:** N/A (sequential)
**Notable:** Camera reuse on stop/start required a guard in `FaceFollower.start()` — `Picamera2` can't be re-opened after `stop()` without `close()`. Sound direction angle mapping (360° sensor → ±80° yaw) was straightforward once the sensor API was confirmed.

---
