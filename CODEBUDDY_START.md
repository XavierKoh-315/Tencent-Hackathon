# Your first CodeBuddy development session

Open the entire `ryde_dispute_starter` folder in CodeBuddy. Paste the prompt below
into its project chat. Let it inspect the files, implement the feature and explain
the change. Save a screenshot of that real conversation for hackathon evidence.

## Prompt 1: inspect and implement

```text
I am building the Ryde ride-hailing dispute-resolution hackathon project.
Read README.md, app.py, disputes/core.py, disputes/adp.py, disputes/prompts.py and
data/policy.json before changing anything.

The required core is a Rider Advocate, Driver Advocate and impartial Judge,
handling route deviation and no-show charges using text/structured evidence.
The starter has an offline deterministic demo and an ADP live-AI adapter.
Explain how evidence retrieval, role isolation and the policy check currently work.

Then implement an evidence timeline in the Streamlit Evidence tab. Combine chat
messages and available pickup events (arrival, GPS observations and cancellation),
sort them by their actual timestamps and display them in Asia/Singapore time.
Clearly label recorded claims versus GPS observations. Handle route cases and
missing timestamps gracefully. Keep offline/live labels and demo-policy notices.
Never read, print or paste .env or secret values into the conversation.

Keep the existing monetary calculations and provider adapter unchanged.
Run the existing tests and explain how to run the revised local application.
```

## Prompt 2: after your first actual ADP run

```text
I have run a dispute using ADP live AI. Review the captured output I provide,
with all credentials removed. Check that each advocate retrieved evidence and
cited an existing policy clause, and that the judge's amount matches the
Python-calculated constraints. Identify any factual claims unsupported by the
retrieved records. Fix any concrete issue you find and describe the change.
Do not count the offline demonstration as AI accuracy.
```

## Prompt 3: after both categories work

```text
Read the completed project and prepare a concise development-process note for
the hackathon submission. Describe the actual CodeBuddy work in this session,
the ChatGPT-prepared starter, our model configuration and measured test results.
Distinguish mock provider-contract tests from live model evaluation.
List any remaining limitations. Do not invent screenshots, metrics or features.
```

Save genuine screenshots across planning, implementation and verification.
Three copies of one screenshot do not show three development interactions.
Actual test results and your CodeBuddy modifications should be committed with
the project source; `.env`, `.venv` and local runtime case logs are ignored.
