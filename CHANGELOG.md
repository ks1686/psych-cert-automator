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

### Added

- Warnings for certificates that convert to two pages or contain characters the template fonts cannot print.

### Security

- The desktop app starts the local API on a random port with a per-launch random token that every request must carry. `/shutdown` requires a JSON body.
- The file opener is limited to the home, Downloads, Documents, and Desktop folders, and the CSP no longer allows inline scripts.

## 1.0.0 - 2026-10-13

First stable release of the certificate generator. The desktop app, CLI, and templates below are what this version actually ships. Earlier 0.2.x notes live on GitHub Releases.

### Fixed

- Certificate of Attendance is one portrait page, with the GSAPP logo in the letterhead and the Jessica Benas signature above the signature line. The recipient name sits between "This is to certify that" and the attended sentence. A long name and title still fit. The stray street-address block and the jammed phone and fax line are gone.
- The NASP letterhead is left-aligned. The school name, street, URL, and phone stay on their own lines, and the logo no longer collides with that text.
- A New York certificate with no license number leaves the license line blank instead of printing an unfilled "NY Psychology License #" label.

### Added

- Layout checks for APA, NY, NASP, NBCC, and Certificate of Attendance, including long names, accents, apostrophes, hyphens, a missing NY license, and in-person locations.
- Golden PNG fixtures rendered with pdftoppm at 96 DPI. A later render must stay within 0.1 percent of those pixels. Poppler 24.02 on Ubuntu 24.04 is the raster used for the fixtures. Tests pin Californian FB to Tinos and Arial Unicode MS to Ubuntu's Noto Sans so the pixels do not follow whichever fonts happen to be installed.
