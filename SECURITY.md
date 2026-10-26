# Security

Please report vulnerabilities privately through
[GitHub security advisories](https://github.com/gsus67/omarchy-taskbar/security/advisories/new)
instead of a public issue.

Every change runs, in CI:

- static QML checks: every text element renders plain text (window titles can
  come from any web page) and the QML references no remote URL;
- CodeQL `security-extended` analysis of the workflows.
