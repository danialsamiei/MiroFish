# QEngin Operator Guide

## Overview

QEngin is the operator dashboard for defining, running, monitoring, and exporting analytical notebooks on top of the MiroFish backend. It is intended for structured analysis workflows where an operator starts with a raw question or operational problem and turns it into a reviewable output.

Primary route:

- `https://engin.gantor.ir/engine/`

Primary functions:

- Define a notebook from a raw topic
- Ask the wizard to suggest an initial configuration
- Run the notebook and monitor live progress
- Inspect logs and diagnostics
- Review results
- Export output as `HTML`, `Markdown`, or `JSON`

## Menu Structure

Top menu items currently exposed in the dashboard:

- `داشبورد`
  - Main workspace for notebook creation and quick status review
- `راهنما و خدمات`
  - Embedded operator guide, service scope, security notes, expected inputs and outputs, and ready-made examples
- `وضعیت سیستم`
  - Runtime and backend health view
- `+ نت‌بوک جدید`
  - Focused path for creating a new notebook
- `خروج`
  - Session termination

## Authentication And Security

Access model:

- The dashboard uses operator accounts
- Authentication is handled through signed token-based sessions
- Session state is stored with secure cookie/token semantics and expires after a limited duration
- Operators should never store passwords, API keys, or private keys in notebook notes

Operational security guidance:

- Credentials must be distributed out-of-band by the system administrator
- The UI must not display live plaintext passwords
- Exported files should be handled according to their sensitivity
- Operator notes are for analytical direction, not secret storage

## Expected Inputs

The main notebook creation workflow expects these fields:

- `موضوع تحلیل`
  - Required
  - A concise, analysis-ready problem statement
  - Example: `اثر بسته شدن تنگه هرمز بر بازار انرژی و بیمه دریایی`
- `مدل اجرا`
  - Optional
  - If omitted, the system falls back to configured defaults
  - Example: `gpt-4o`
- `حالت تحلیل`
  - Optional but recommended
  - Controls the style and purpose of the output
  - Example values:
    - `strategic-brief`
    - `market-impact`
    - `risk-early-warning`
    - `scenario-analysis`
    - `executive-memo`
- `عمق تحلیل`
  - Optional
  - Balances speed versus depth
  - Example values:
    - `rapid`
    - `standard`
    - `deep`
- `سقف منابع OSINT`
  - Optional
  - Approximate number of sources to synthesize
  - Recommended range: `6` to `10`
- `یادداشت اپراتور`
  - Optional
  - Additional boundaries, priorities, or focus hints

## Expected Outputs

Each notebook may produce the following operational artifacts:

- `Status`
  - `draft`
  - `configured`
  - `running`
  - `complete`
  - `failed`
  - `cancelled`
- `Logs`
  - Step-by-step execution records
  - Includes stage name, timestamps, progress, and diagnostic messages
- `Diagnostics`
  - Pipeline behavior
  - Source counts
  - Stage timing
  - Export readiness
- `Results`
  - Executive summary
  - Key findings
  - Recommended actions
  - Scenarios or structured insights where applicable
- `Exports`
  - `HTML` for presentation and distribution
  - `Markdown` for editing and publishing workflows
  - `JSON` for machine ingestion or downstream automation

## Operational Workflow

Recommended operator sequence:

1. Define the analytical problem precisely.
2. Use the wizard if the topic is still rough.
3. Create or configure the notebook.
4. Start the run.
5. Watch `Logs` for stage-by-stage progress.
6. Review `Diagnostics` if the run is weak, slow, or failed.
7. Review `Results`.
8. Export in the format best suited to the audience.

## Embedded Example Scenarios

The guide menu includes ready-to-apply scenarios that automatically prefill the notebook form:

- `تحلیل اثر بسته شدن تنگه هرمز`
  - Focus on energy, insurance, shipping, and short-term shock scenarios
- `امنیت کشتیرانی دریای سرخ`
  - Focus on attacks, rerouting, logistics cost, and early-warning indicators
- `اثر تحریم بر زنجیره تامین`
  - Focus on supply chain pressure, payment rails, parallel markets, and policy response

## When To Stop Or Re-Run

Cancel or rerun when:

- The topic was entered incorrectly
- The wrong model or mode was chosen
- The run takes too long and a smaller source limit is more appropriate
- Diagnostics indicate a weak fallback result and a stronger rerun is justified

## Quality Checklist

Before handing off results:

- Confirm the executive summary matches the original question
- Check whether key findings are source-backed or at least operationally coherent
- Verify that recommended actions are actionable rather than generic
- Confirm the source volume and analysis depth are suitable for the task
- Export the output in the right format for the intended consumer

## Troubleshooting Notes

Common issues:

- Empty or low-quality result
  - Revisit topic clarity, model choice, and source limit
- Failed notebook run
  - Review logs and diagnostics first
- Output is too generic
  - Add stronger operator notes and rerun
- Execution is too slow
  - Lower source limit or reduce analysis depth

## Service Scope

QEngin currently serves as:

- An operator cockpit
- A notebook execution interface
- A live monitoring surface
- A structured export layer
- A human-review step before handoff to other systems

It is not merely a static dashboard. It is the operational surface for controlled analytical runs on the Qadr ecosystem.
