# Releases

Finished, signed builds land here; `clients/android/scripts/release.py build` (and `release`) writes them.

```
ifinmail-android-<version>-<build>.apk          the signed APK that is uploaded to the server
ifinmail-android-<version>-<build>.apk.sha256   its SHA-256, in `sha256sum -c` format
```

The binaries are git-ignored (the server is the system of record: Settings → App releases). Release
notes live in `clients/android/release-notes/<version>.md`. How to cut and publish a release:
`docs/android-releases.md`.
