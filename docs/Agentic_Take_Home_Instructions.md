# Take-Home Technical Assessment
## M&A Acquirer Identification Engine
AI Innovation Team • Investment Banking Division

| | |
|---|---|
| **Time Allotment** | 3–4 hours |
| **Submission** | GitHub repo or zip file |
| **Deadline** | 72 hours from receipt |
| **Format** | Runnable prototype + README |

**Timing note:** We expect approximately 3-4 hours of focused work. The 72-hour window is for scheduling flexibility, please do not spend the full 72 hours on this.

## 1. Background & Context

Our AI Innovation Team builds proprietary tools that compress deal timelines and surface insights faster than our competitors. One of the highest-leverage problems in M&A advisory is acquirer identification: given a target company, which buyers are most likely to transact, and why?

Today, a junior banker spends 2-4 hours on this task: pulling comps from Pitchbook, scanning prior transactions in CapIQ, synthesizing rationale in PowerPoint. We want to reduce that to under 3 minutes, at MD-ready quality.

## 2. The Problem Statement

**Banker Ask:** I need to quickly identify the 10 most likely acquirers for a $200M healthcare services company and generate a one-page rationale for each.

You are provided with a dataset of 500 historical M&A transactions (CSV). The dataset includes the following fields:

| Field | Description |
|---|---|
| `target_company` / `acquirer` | Company names (real company names used for acquirers; semi-fictional for targets) |
| `sector` / `sub_sector` | Healthcare Services, Health IT, Pharma/Biotech, Medical Devices, Dental, Behavioral Health, and more |
| `deal_size_mm` | Enterprise value of the transaction in USD millions |
| `deal_type` | Strategic Acquisition, Bolt-on, Carve-out, LBO, Merger of Equals, etc. |
| `ev_ebitda_multiple` / `ev_revenue_multiple` | Transaction valuation multiples |
| `ebitda_margin_pct` / `revenue_growth_pct` | Target company financial profile at time of deal |
| `geography` | Northeast, Southeast, Midwest, National, etc. |
| `acquirer_type` | Strategic vs. Financial Sponsor (Private Equity) |
| `strategic_rationale_tags` | Pipe-delimited tags: e.g. Geographic Expansion\|Platform Build\|Cost Synergies |
| `outcome` | Closed, Withdrawn, Pending, Terminated |
| `deal_year` / `deal_quarter` | When the transaction was announced |

**Data note:** Acquirer names are real companies; target names are semi-fictional. The dataset is skewed toward financial sponsors (PE firms) as acquirers—this is intentional and reflects real market dynamics. The Healthcare Services sector has 46 transactions, with only ~12 in the $100–400M range. Strong candidates will think carefully about how to use adjacent sectors and the full dataset rather than filtering narrowly.

## 3. Deliverables

### 3.1 Working Prototype

Build a runnable application that takes the provided CSV and, given the target profile below, outputs the 10 most likely acquirers with a one-page rationale for each.

**Target Profile:** Sector: Healthcare Services | Deal Size: ~$200M EV | Profile: Mid-market, private, regional, strong EBITDA margins

Your prototype must:
- Accept the provided CSV as its primary data source (no external database required)
- Use an LLM to generate or synthesize the acquirer rationale—not just filter/sort rows
- Produce output for all 10 acquirers in a format a banker can act on
- Be runnable with a single command or URL, no manual setup beyond standard dependencies

### 3.2 One-Page Rationale per Acquirer

Each rationale should address the following elements. You decide the format (PDF export, web UI, structured text), but the content must be present:

| # | Section | What We Expect |
|---|---|---|
| 1 | Acquirer Overview | Who they are: size, strategic priorities, recent M&A activity implied by the dataset |
| 2 | Strategic Fit Thesis | Why this target makes sense for this acquirer specifically—grounded in the data |
| 3 | Precedent Activity | Relevant prior transactions from the dataset: sector, size, deal type, multiples |
| 4 | Valuation Context | Relevant EV/EBITDA and EV/Revenue comps from comparable closed deals in the CSV |
| 5 | Risk Flags | At least 2 risks: e.g. antitrust, integration complexity, financing capacity, competitive process |
| 6 | Conviction Level | High / Medium / Low with 1-2 sentence rationale tied to data signals |

### 3.3 README

Include a concise README that covers:
- How to run the prototype (single command preferred)
- Architecture decisions: how you structured the LLM prompt, how you use the CSV, what you would improve given more time
- Any assumptions made about the target company or dataset
- Known limitations or failure modes
- How you handle output non-determinism (e.g. caching, seed values, or acknowledgment that outputs may vary between runs)

## 4. Constraints & Ground Rules

- **Allowed:** Use any LLM provider and any programming language or framework.
- **Suggested:** Anthropic Claude, OpenAI GPT-4o, or open-source models via Ollama
- **Acceptable formats:** Streamlit app, FastAPI + React, Jupyter notebook with narrative, CLI tool
- **Data:** The CSV is your only required data source. You may augment with public information (Wikipedia, SEC filings) but it is not expected or required.
- **No shortcuts:** Do not hardcode a ranked list of acquirers. The LLM and/or your algorithm must derive them from the data.
- **Integrity:** All code must be your own work. You may use open-source libraries freely. Be prepared to explain any part of your code in a follow-up interview.
- **Scope:** You have 72 hours. We are not expecting perfection, we are evaluating how you think, not just what you build.

## 5. Evaluation Criteria

| Criterion | Weight | What We're Looking For |
|---|---|---|
| Problem Decomposition | 20% | Does the candidate understand the actual banker workflow? Is the solution addressing the right problem? |
| LLM Prompt Design | 20% | Are prompts thoughtfully structured? Do outputs feel tailored, or generic? |
| Output Quality | 20% | Would a VP send this to an MD without editing? Is it specific, not generic? |
| Data Thinking | 15% | Is the CSV used intelligently? Are multiples, deal types, sector signals, and acquirer-type distinctions leveraged well? |
| Code Quality | 15% | Clean, modular, documented. Handles edge cases. Not just 'works on my machine.' |
| Iteration Mindset | 10% | Are tradeoffs acknowledged? Is the architecture extensible? Is the README honest? |

**Note:** A clean, well-reasoned CLI tool with excellent prompts will outscore a polished UI with shallow LLM usage.

## 6. What "Good" Looks Like

A strong submission will feel like a tool a banker would actually open on deal day. Concretely:
- The 10 acquirers should have distinct, thorough, and data-backed rationale with explainability built-in, not 10 variations of the same generic rationale
- Each rationale cites specific signals from the data: "This acquirer has completed 6 Healthcare Services deals in the $150-300M range with a median EV/EBITDA of 13.2x"
- Conviction levels vary across acquirers and the reasoning is defensible
- The prototype runs end-to-end in under 60 seconds
- The README is honest about what's missing and how you'd improve it

A weak submission will produce generic LLM boilerplate ("This acquirer is a leading healthcare company with a track record of strategic acquisitions…") that could apply to any target.

## 7. Stretch Goal (Optional)

If you finish the core deliverables and want to go further, consider one of the following:
- Extend the prototype to accept arbitrary target profiles (sector, size, geography) rather than a single hardcoded target
- Add a comparison mode that generates side-by-side acquirer analysis for two different targets
- Build a simple feedback loop where a user can flag a recommended acquirer as irrelevant and the system adjusts

This section is entirely optional and will not count against you if omitted. It exists to give strong candidates room to differentiate.

## 8. Submission Instructions

- Submit a GitHub repository (preferred) or a .zip file to your recruiting contact
- The repository should include: all source code, the README, and any sample output you want us to see
- Do not include your API keys in the submission, use environment variables and document them in the README
- If your prototype requires a paid API key to run, include a recorded demo (Loom or equivalent) in the README

Questions? Reach out to your recruiting contact. We will not provide hints on the approach, that is part of the assessment.

Good luck.
