# Changelog

## Unreleased

### Fixed

- Attendance is checked against the session start and end times entered in the app or CLI, not the Zoom meeting's own start and end.
- Only exact name matches are accepted automatically. Partial matches such as "Li Ma" against "Li Wong", or "Sam Rivera" against "Sam", are marked Needs review and need an explicit Include. Email confirms a match or breaks a tie.
- Template placeholders are replaced in one pass, so a title containing words like NAME, TITLE, or DATE prints as typed.
- CE credits accept quarter steps such as 1.5 and print without a trailing ".0". The app and CLI reject other values.
- Duplicate survey submissions for the same person and CE type keep only the latest one. Unfinished Qualtrics responses are dropped.
- Zoom attendees with the same name but different emails are kept apart.
- Names are compared after Unicode, accent, and apostrophe normalization.
- Zoom and Qualtrics reports can be `.xlsx` or `.csv`, with Qualtrics' three header rows or an extra Zoom title row. An unreadable file is a 400 with a message, not a 500.
- The CLI leaves out the Zoom host unless `--include-host` is passed.
- Rerunning into the same output folder no longer overwrites earlier certificates or the report.
- Preview uses the local date for the issue date, like generation.
- Two different people who share a name, or who share one email address, are no longer merged into one person. Earlier duplicate submissions are listed in the report as Duplicate.
- Rejoining before the session starts or after it ends no longer counts as a gap.
- When the Zoom meeting ran shorter than the entered session, attendance is judged over the overlap and a warning says so.
- A damaged `.xlsx` is reported as unreadable (400) instead of a server error (500).
- The Zoom host is found in Zoom web CSV exports from the meeting's User Email.
- Filenames use the real surname, so "Mark Roe, Ph.D." gives `Roe_...`, and all-caps names such as "KIM LI MA" keep their surname.
- Page counts work for PDFs that store pages in compressed object streams.
- A rerun that writes `X_2.pdf` or `ineligibility_report_2.xlsx` says which file is the current one.

### Added

- Warnings for certificates that convert to two pages or contain characters the template fonts cannot print, in generation results and in Preview.
- `bun run tauri dev` uses port 8008 and a fixed development token, and reuses an API already running there. Release builds keep the random port and token.

### Security

- The desktop app starts the local API on a random port with a per-launch random token that every request must carry. `/shutdown` requires a JSON body.
- The file opener is limited to the home, Downloads, Documents, and Desktop folders, and the CSP no longer allows inline scripts. The CSP allows only the API's actual port.
- The launch token is accepted only in a header, never in a URL. PDF links carry only the file's own unguessable token.

## 1.0.0 - 2026-10-13

First stable release of the certificate generator. The desktop app, CLI, and templates below are what this version actually ships. Earlier 0.2.x notes live on GitHub Releases.

### Fixed

- Certificate of Attendance is one portrait page, with the GSAPP logo in the letterhead and the Jessica Benas signature above the signature line. The recipient name sits between "This is to certify that" and the attended sentence. A long name and title still fit. The stray street-address block and the jammed phone and fax line are gone.
- The NASP letterhead is left-aligned. The school name, street, URL, and phone stay on their own lines, and the logo no longer collides with that text.
- A New York certificate with no license number leaves the license line blank instead of printing an unfilled "NY Psychology License #" label.

### Added

- Layout checks for APA, NY, NASP, NBCC, and Certificate of Attendance, including long names, accents, apostrophes, hyphens, a missing NY license, and in-person locations.
- Golden PNG fixtures rendered with pdftoppm at 96 DPI. A later render must stay within 0.1 percent of those pixels. Poppler 24.02 on Ubuntu 24.04 is the raster used for the fixtures. Tests pin Californian FB to Tinos and Arial Unicode MS to Ubuntu's Noto Sans so the pixels do not follow whichever fonts happen to be installed.
