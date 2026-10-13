# Changelog

## 1.0.0 - 2026-10-13

First stable release of the certificate generator. The desktop app, CLI, and templates below are what this version actually ships. Earlier 0.2.x notes live on GitHub Releases.

### Fixed

- Certificate of Attendance is one portrait page. The recipient name sits between "This is to certify that" and the attended sentence. The stray street-address block and the jammed phone and fax line are gone.
- The NASP letterhead is left-aligned. The school name, street, URL, and phone stay on their own lines, and the logo no longer collides with that text.
- A New York certificate with no license number leaves the license line blank instead of printing an unfilled "NY Psychology License #" label.

### Added

- Layout checks for APA, NY, NASP, NBCC, and Certificate of Attendance, including long names, accents, apostrophes, hyphens, a missing NY license, and in-person locations.
- Golden PNG fixtures rendered with pdftoppm at 96 DPI. A later render must stay within 0.1 percent of those pixels. Poppler 24.02 on Ubuntu 24.04 is the raster used for the fixtures.
