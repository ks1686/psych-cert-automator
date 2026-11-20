# Review matches

After parse, the wizard matches Zoom names to Qualtrics names. The user sees counts for matched, ambiguous, and not found rows, and can leave someone out with the row checkbox. The Zoom host is checked for exclusion already.

## Sub-features

- `review-counts` shows how many names matched, how many are ambiguous, and how many were not found.
- `review-host` shows the Zoom host row with the `Host` checkbox already checked, so the host is excluded.
- `review-continue` moves the included rows on to certificate generation.

## How to get to it (user POV)

- On Upload Files, after the parse status is visible, choose Next.
- The card heading is `Review Name Matches`.
- The summary badges and the per-row checkbox are on that card. The host row reads `Host` on its checkbox. Other rows read `Skip`.

## Driving it with verify-psych-cert-gen

Preconditions:

- Upload has parsed the pilot fixtures and shows `14 participants found, 14 CE requests found`.

Packaged check: `verify-psych-cert-gen drive --id RUN_ID review-matches`.

- **Open the review.** Run `verify-psych-cert-gen browser --id RUN_ID -- click-role button Next`, then `verify-psych-cert-gen browser --id RUN_ID -- wait-heading "Review Name Matches"`. The heading is `Review Name Matches`.
- **Read the counts.** Run `verify-psych-cert-gen browser --id RUN_ID -- expect-text "11 matched"`, then the same op for `1 ambiguous` and `1 not found`. Each badge is visible.
- **Confirm the host.** Run `verify-psych-cert-gen browser --id RUN_ID -- expect-host "Morgan Hale"`. The Morgan Hale row's checkbox is checked and the row shows `Host`.

## Gotchas

- The host name comes from the Zoom workbook. The pilot host is Morgan Hale. A different export names a different host, and the checkbox label is still `Host`.
- Leaving the host checked means that person gets no certificate. The generate proof requires the PDFs to omit Morgan Hale.
- Ambiguous rows are left out until the user includes them. The pilot journey does not click `Include this match` or `Apply Corrections`. The eligible count on the next step is 8 with that default.
- Badge text is the whole badge: `11 matched`, not a separate number and a separate word, for the exact text check.
