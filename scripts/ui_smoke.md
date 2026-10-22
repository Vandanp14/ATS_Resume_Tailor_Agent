# UI smoke checklist

Runs the web UI against a fake pipeline. No Gemini quota is used and nothing
outside the throwaway data folder is touched.

```bash
.venv/bin/python scripts/ui_smoke_server.py
```

Open http://127.0.0.1:8765. The server queues two jobs on start (about 20
seconds to finish) and seeds one old command-line folder. Do each pass at
1440px wide and again at 390px.

1. **New resume.** Paste a job description, company, and role. Press
   **Check skills**; the "Do you know these?" chips appear. Tick one. The
   button reads **Tailor resume**; press it.
2. **Running.** The page moves to `#job/<id>`. Five steps, the track across
   the top fills in, the page on the right inks in, elapsed time counts up.
   A plain note "Gemini is busy, so it's using a backup model." shows during
   Match your experience. The top bar shows "<Company>: <step>" and links
   back here.
3. **Done.** Big keyword-match percentage, "Everything your resume states is
   included", one amber "Not on your resume: Section 508, ADA" note, green
   **Download PDF**, **Tailor again**, **Delete**. PDF preview on the right.
   **Details** opens Activity / Review / Files.
4. **History.** Lists the jobs with Ready / Running / Failed / Queued tags.
   No old command-line folder rows.
5. **Select and delete.** **Select** → tick **Select all finished** and
   **Old command-line folders (1)** → **Delete N resumes** → the dialog lists
   them, says it can't be undone, and how much space it frees → **Delete**.
   A toast says "Deleted N resumes. <size> freed." and the list updates.
6. **Single delete.** Open a finished job → **Delete** → confirm → back on
   History with the toast.
7. **Missing job.** Open `#job/<id>` for a deleted job: History shows
   "That resume no longer exists."
8. Browser console shows no errors.

Save screenshots of New resume, Job (running), Job (done), History, and
Delete confirm at both widths under `.playwright-mcp/ui-refresh/`.
