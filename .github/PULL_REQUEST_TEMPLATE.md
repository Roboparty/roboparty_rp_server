---
name: Pull Request
about: Submit a code change
---

<!-- Check the PR type -->
- [ ] 🐛 Bug fix
- [ ] ✨ New feature
- [ ] 📦 Packaging (debian/ changes)
- [ ] 📝 Docs
- [ ] 🔧 CI / workflow

## Description

<!-- Briefly describe what this PR does -->

## Version Check

<!-- Confirm if version is affected -->

- [ ] This change does NOT bump version
- [ ] Updated debian/changelog

## Testing

- [ ] Build passes: `dpkg-buildpackage -us -uc -b`
- [ ] Tested on [amd64 / arm64]
- [ ] Notes:
