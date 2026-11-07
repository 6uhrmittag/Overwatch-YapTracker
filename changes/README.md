# Changelog fragments (#494)

Every PR adds **one file here**, `changes/<issue>.md`, instead of editing `CHANGELOG.md`, so PRs
waiting behind each other never conflict over it. It holds the PR's "What you can see now":

```
### Faster checks on every change (#493)
- Behind the scenes: the automatic checks run in about half the time.
```

First line `### <title> (#<issue>)`, then the bullets. A second PR for the same issue: `changes/<issue>-2.md`.
`tests/test_changelog.py` checks every file here in the PR. After the merge, the pre-release job
(`tools/changelog.py`) moves them into `CHANGELOG.md`, dated the day they were merged, newest
first, on top of its first `## ` section, and deletes the file. After a stable release, add the
next `## v1.x: on the way to v1.x.0` heading to `CHANGELOG.md` by hand. The release notes still
come from the PR's "What you can see now".
