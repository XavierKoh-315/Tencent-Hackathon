# Install this update

This ZIP is a patch for the latest `GPT(1).zip` project you supplied. It is not a standalone project. It completes the human-review form and improves the existing colours and cards. It does not change your published ADP prompts, keys, tools or case datasets.

## 1. Copy the files into the correct folder

1. Stop local Streamlit if it is running: press Ctrl+C in its terminal.
2. Make a backup copy of your existing project folder.
3. Extract `Ride_Dispute_Update.zip` into a separate temporary folder.
4. Open your existing project folder containing `app.py`, `requirements.txt`, `disputes` and `data`. This is normally your inner `ryde_dispute_starter` folder, not the parent Downloads folder.
5. Copy all the extracted ZIP contents into that existing project folder. Merge the `disputes` and `tests` folders. When Windows asks, choose **Replace the files in the destination** for the files supplied in this patch.
6. Keep the rest of your project. Do not delete or replace your `.env`, `.git`, virtual environment, original datasets or other unrelated files. No credentials are included in this ZIP.

If there is no Replace prompt, check that the new `app.py` is in the same folder as the old `app.py`; avoid an extra nested folder.

## 2. Install and run locally

Open a terminal in that project folder. Activate your existing virtual environment if you use one, then run:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open the localhost address printed by Streamlit. Dependencies include the tested Streamlit version 1.66.0. Your existing ADP key stays in your local `.env` or environment; never paste it into chat or GitHub.

Local human reviews use `runtime/human_reviews.sqlite3` unless `DATABASE_URL` is set in the terminal environment. That local database is not automatically synced to Render. For local PostgreSQL testing, export `DATABASE_URL` in the terminal before starting Streamlit; use a connection address reachable from your computer.

## 3. Configure saving on Render

Your Streamlit website is https://ride-dispute-review.onrender.com/.

The review form needs a reachable PostgreSQL database for durable hosted storage. On the **Streamlit web service**, add `DATABASE_URL` with the database's PostgreSQL connection string. Keep it private, just like your ADP key. Use your database provider's connection details; an internal/private address only works from a service on the appropriate private network. No database has been created or connected on your behalf.

The table and indexes are created automatically when the app connects, so the database user needs permission to create them. `psycopg2-binary` is in requirements.txt. If storage is unavailable, the AI result still displays and the review form explains the problem; it will not pretend that a decision was saved. Saving locally does not prove the hosted database is configured.

Your existing ADP environment variables remain necessary for investigations. This patch needs no agent-tool URL changes and no changes to your FastAPI service environment variables.

## 4. Push the update

From the project folder, inspect your changes first:

```bash
git status
```

Then stage only the supplied files:

```bash
git add app.py human_review_store.py disputes/core.py requirements.txt README.md UPDATE_GUIDE.md VALIDATION.md verify_cases.py tests/test_human_review_store.py tests/test_organiser_integration.py tests/test_app_workflow.py tests/test_review_regressions.py validation/local_verification.json
git commit -m "Complete human review workflow and refine Streamlit layout"
git push
```

If there is nothing to commit, do not force a commit. If push reports a branch/upstream or merge error, resolve that reported issue rather than force-pushing. Deployment depends on each Render service's configured branch and auto-deploy setting. Once deployed, open the Streamlit link above and refresh the page. Inspect deployment logs if the new build fails.

## 5. Verify without spending tokens

```bash
python verify_cases.py
python -m unittest discover -s tests -v
```

The first command checks all eight local policy baselines. The tests use local fixtures and controlled responses, not the published ADP agents. Both use **zero ADP tokens**. Avoid pressing Investigate repeatedly just to inspect layout: results are reused when switching away from a completed case and back during the same session.

## 6. Optional real ADP check

Only when your key is configured privately and you have tokens:

```bash
python verify_cases.py --live --cases NS02
```

This explicitly spends tokens for one live request. NS02 is a simple layout smoke case; its token usage has not been measured here and is not guaranteed to be the lowest. The runner does not send the expected answer to ADP, does not retry automatically, and stops after the first failed request. Results go to `runtime/live_verification.json`.

To test the full set, explicitly select them:

```bash
python verify_cases.py --live --cases NS01 NS02 NS03 NS04 RT01 RT02 DISP-001 DISP-003
```

No live ADP tests were run when preparing this patch. Account allowance, published prompts, handoffs and tool configuration still determine real agent behaviour. Check the ADP execution trace if you need to verify that both advocates actually completed their reports; the current frontend does not receive separate structured advocate reports.

## 7. Check the human-review feature

1. Investigate NS04 or DISP-001 once to obtain a valid human-review result.
2. The pending recommendation is red and shows the original model confidence, when available.
3. Choose **Review case**, select a decision, enter the reviewer identifier, proposed messages and explanation. A refund requires a positive amount no greater than the verified charge.
4. Save. A final decision becomes green with confidence **—**. Further review stays pending and allows a linked follow-up.
5. Refresh the resulting URL to verify the saved investigation restores without another ADP request. Original AI output remains available in the collapsed section.

The reviewer identifier is a demo name, not verified staff authentication. This records proposed resolutions only: it does not issue refunds or send messages. Use the supplied demonstration data rather than real customer information.
