# Changelog fragments (#494)

Every PR adds **one file here**, `changes/<issue>.md`, instead of editing `CHANGELOG.md`, so PRs
waiting behind each other never conflict over it. It holds the PR's "What you can see now":

```
### Faster checks on every change (#493)
- Behind the scenes: the automatic checks run in about half the time.
```

First line `### <title> (#<issue>)`, then the bullets. After the merge, the pre-release job
(`tools/changelog.py`) moves them into `CHANGELOG.md` under the date, newest first, and deletes
the file. The release notes still come from the PR's "What you can see now".
