# Security

Please report vulnerabilities privately through
[GitHub security advisories](https://github.com/gsus67/omarchy-taskbar/security/advisories/new)
instead of a public issue.

Every change runs, in CI:

- static QML checks: every text element renders plain text (window titles can
  come from any web page) and the QML references no remote URL;
- guards for the commands it runs: every `bash -c` script is made of string
  literals only and receives window data as positional arguments, never pasted
  into the script; other programs start from argument lists, without a shell;
- ShellCheck on standalone scripts and each embedded `bash -c` script;
- CodeQL `security-extended` analysis and zizmor for the workflows;
- OpenSSF Scorecard (weekly and on `main`) for the repository's practices.
