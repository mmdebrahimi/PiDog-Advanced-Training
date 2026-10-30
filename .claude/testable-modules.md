# Testable Modules
<!-- Auto-maintained by /test-epilogue — do not edit manually -->

- deploy/deploy_pidog.py — load_servo_map (csv, fail-closed), PolicyMLP forward pass, scripted_trot_deg, stagger frame construction, run()'s slew-cap clamp (testable with fakes)
- deploy/power_audit.py — audit_stream delta accounting, scripted_crawl_deg reference gait
- eval_npz.py — run_episodes episode accounting (testable with fake env/policy), verdict threshold logic
