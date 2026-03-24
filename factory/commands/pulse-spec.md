---
description: Create or update a feature specification with persona, problem, BDD criteria, and analytics events. Delegates to pulse-product-director.
argument-hint: <feature-name> (e.g., "WIP Monitor", "Sprint Comparison", "Filter Bar")
---
# Spec Feature: **$ARGUMENTS**

Delegate to **pulse-product-director** to create/update:

1. **Persona & Problem**: Which persona (Carlos/Ana/Marina/Priya/Roberto)? What decision does this help them make?
2. **User Story**: As [persona], I want [capability], so that [outcome].
3. **BDD Acceptance Criteria**: Given/When/Then for each scenario (happy path, edge cases, empty state, error state).
4. **Anti-surveillance check**: Does this feature expose individual developer data? If yes → REDESIGN.
5. **Analytics events**: What user actions to track? Map to AARRR funnel.
6. **Release tag**: MVP, R1, R2, R3, R4, or RN.
7. **Visualization**: Which chart type and why (consult pulse-data-scientist if needed).
8. **Dependencies**: Which other features/stories does this depend on?

Output: Update product-spec.md and release-plan.md with the new/updated feature.
