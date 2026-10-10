# OpenDispatch project context

## Purpose

Open-source field service management and ticketing for small blue-collar contractors. The goal is to give small teams job intake, dispatch, and status tracking without requiring expensive per-seat FSM SaaS. Make the project usable on Windows, Linux, and macOS.

## Product direction

- Keep the core useful and free; offer optional paid add-ons and hosting tiers based on team size and needs.
- The self-hosted release keeps scheduling in the local app. External calendar sync is deferred; technician job links remain available.
- Each signed-in worker should land on their own assigned schedule; office dispatchers and owners can use a team/resource schedule.
- Customers should have a live job status view opened from a private link on their invoice, without needing a full account unless that changes later.
- Job document drop zones should accept common image formats broadly rather than limiting uploads to one image extension; consider PDF and other job documents as well.
- Explore maps integrations so customers can see worker distance or arrival progress, subject to privacy and implementation cost.
- AI assistance is optional and limited to helping workers plan their day or week. Never make AI mandatory.
- Wispr Flow / voice input could help workers who find phone typing difficult.
- Brand direction: a gear logo appropriate for service workers.
- Competitors to consider: ServiceM8, Connecteam, Service Fusion, and Kickserv.

## Technical and operating constraints

- Avoid AWS dependencies so self-hosters are not forced into AWS costs.
- Build locally first. GCP dev and prod projects exist for the internship, but billing is currently disabled after the free trial ended. Keep cloud usage low-cost and defer moving workloads until the design and costs are understood.
- Prioritize reliability and low maintenance: field workers need a system that works without spending time fixing it.
- Keep infrastructure and optional integrations replaceable so self-hosting remains practical.

## Security and payments

- Strong login security matters because an intruder could take over a contractor's operation.
- A fun CAPTCHA-style human check is a product idea.
- Suspicious activity should freeze accounts automatically; data destruction should only happen when initiated by the owner.
- Payment integrations for paying 1099 workers after job completion are a future direction. Gusto and Ramp were considered; do not assume either is selected or that the product should handle regulated payroll itself.

## Internship and learning context

- Internship project target: about 200–220 hours, started around September 22, 2026, planned end December 16, 2026, with extension possible.
- GCP is new to the developer and is the planned cloud platform during the internship, while local-first development and low cost remain important.
- The developer wants to explore AI/ML features and is learning ML from a beginner level; prefer explainable, incremental work and avoid making ML a prerequisite for the core product.

## Repository

- GitHub: `github.com/milesjo-cloud-project/opendispatch`.
- Use the existing repository architecture and conventions when implementing features. This file records product goals and constraints, not a mandate to add every listed idea to the current milestone.
