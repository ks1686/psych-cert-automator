# Generate certificates

The last step previews one certificate, writes one PDF per eligible person, and can download those PDFs as a zip. The user picks an output folder first. The files are the proof: the names, the date, and the credit hours have to be inside the PDF text.

## Sub-features

- `generate-preview` draws a certificate preview on the page.
- `generate-write` writes one PDF per eligible person and an ineligibility workbook.
- `generate-contents` puts the attendee name, the training date, the instructor, the title, and the credit hours in the PDF text.
- `generate-zip` downloads the same PDFs in one zip.
- `generate-widths` shows the finished step at desktop, tablet, and 375px widths.

## How to get to it (user POV)

- On Review Name Matches, choose Next.
- The card heading is `Generate Certificates`.
- Choose `Preview Certificate`, then `Choose output folder`, then `Generate All Certificates`.
- After the list appears, `Download All as ZIP` saves the archive. `Open output folder` is a separate control and this journey leaves it alone.

## Driving it with verify-psych-cert-gen

Preconditions:

- Review shows `11 matched`, `1 ambiguous`, `1 not found`, and the Morgan Hale host checkbox is checked.
- The run output directory is empty.
- `pdftotext` is on `PATH`.

Packaged check: `verify-psych-cert-gen drive --id RUN_ID generate-certificates`. This is the journey a full proof runs. It starts from `/` and includes metadata, upload, and review before the steps below.

- **Open generate.** Run `verify-psych-cert-gen browser --id RUN_ID -- click-role button Next`, then `verify-psych-cert-gen browser --id RUN_ID -- wait-heading "Generate Certificates"`. The status line is `8 eligible certificates ready to generate.` Confirm with `verify-psych-cert-gen browser --id RUN_ID -- expect-text "8 eligible certificates ready to generate."`.
- **Preview.** Run `verify-psych-cert-gen browser --id RUN_ID -- click-role button "Preview Certificate"`, then `verify-psych-cert-gen browser --id RUN_ID -- wait-canvas`. A canvas is visible.
- **Choose the folder.** Run `verify-psych-cert-gen browser --id RUN_ID -- click-role button "Choose output folder"`, then `verify-psych-cert-gen browser --id RUN_ID -- expect-output output`. The folder line includes the path suffix `output`. Generate stays disabled until this click.
- **Generate.** Run `verify-psych-cert-gen browser --id RUN_ID -- click-role button "Generate All Certificates"`, then `verify-psych-cert-gen browser --id RUN_ID -- expect-text "Generated Certificates (8)" 120`. The list shows `Avery Chen` and `Riley Okonkwo`.
- **Capture the screen.** The drive saves viewport screenshots `generate-desktop.png` (1280x900), `generate-tablet.png` (768x1024), and `generate-mobile.png` (375x812), plus full-page copies `full-generate-desktop.png`, `full-generate-tablet.png`, and `full-generate-mobile.png`, and `generate.aria.txt`, into the evidence directory.
- **Read the PDFs.** The drive runs `pdftotext -layout` on the new PDFs. The proof requires exactly 8 PDFs and one `ineligibility_report.xlsx`, and no other new file. The folded text contains `Avery Chen`, `October 6, 2026`, `Amira Solano`, `Ethics and Practice in School-Based Mental Health`, and `CE CREDITS: 3` or `CE CREDIT HOURS: 3`. It does not contain `Morgan Hale`. Evidence gains `pdf-text.txt` and `pdf-names.txt`.
- **Download the zip.** Run `verify-psych-cert-gen browser --id RUN_ID -- download-zip <state>/output/certificates.zip`. The archive contains 8 PDF members.

## Gotchas

- Generate into an empty directory. A folder that already contains PDFs from this session writes `LastName_..._2.pdf`, and a later count of "new" files can mix the two runs.
- A failed PDF conversion writes a `.docx`. `prove-pdfs` then fails, including when 8 PDFs are also present. A Word file is not a successful certificate for this proof.
- Do not click `Open output folder`. The opener is stubbed in `VITE_E2E=1`, and the click is outside the proof.
- At 375px the top nav hides the step labels (`hidden sm:inline`). The viewport screenshot is 375 pixels wide. The full-page copy can be wider when a table overflows. Judge the mobile shot by the `Generate Certificates` heading.
- The eligible count is 8 because the host, the ambiguous row, and the not-found row are excluded. Changing those checkboxes changes the PDF count and the zip count together.
- Credit lines differ by template. APA pages say `CE CREDITS:`. NBCC pages say `CE CREDIT HOURS:`. The proof accepts either line when the number is 3.
