# Cosmos Employee Portal Android test app

Android wrapper for https://cosmos-ecosystem-staging.onrender.com/.
The user selected the live employee portal. That portal differs from this repository's standalone attendance template. This Android directory deliberately opens the selected portal and does not deploy or change either backend.

## Included

- Existing portal login, modules and server-side attendance rules.
- HTTPS-only WebView; exact host allowlist; external links open outside the app.
- Location permission requested only when the website requests GPS. Android approximate-only permission is rejected with a settings hint because the portal validates accuracy.
- Camera permission only if the trusted portal requests video capture. Microphone requests are not granted.
- Native reload, browser fallback, back navigation and connection error/retry screen.
- Website file picker; authenticated same-origin downloads and browser blob exports up to 10 MB, saved through Android's document picker.
- No JavaScript/native bridge, local-file access, third-party cookies, background location, or hardcoded credentials.

Minimum Android 8.0 (API 26); target SDK 35. Requires internet, an up-to-date Android System WebView, and the existing online service. This is an internal test APK, not a Play Store release. The app does not add offline attendance, geofencing, face recognition or liveness checks; those remain server/site features.

## Build

Install JDK 17 and Android SDK tools. Install `platforms;android-35` and `build-tools;35.0.0` through sdkmanager, reviewing the SDK licence. Set `ANDROID_SDK_ROOT` to your SDK directory.

```bash
cd android
./build-test-apk.sh
```

Output: `build/Cosmos_Employee_Portal_Test.apk`. The script runs the URL-policy tests, compiles resources and Java, creates DEX, aligns the package and signs/verifies the APK with a local test keystore. It builds directly with Android SDK tools; Gradle is not required. If the host has only a JRE, it can use an Eclipse compiler jar via `COSMOS_ECJ_JAR`. Production builds should use a JDK.

The test key is local to the builder and excluded from Git. Keep it locally if you want subsequent APKs to update this installation. A separately generated CI test key may require uninstalling the previous test app before installation. Use a company-controlled release signing key for employee rollout; never commit it or send it in chat.

## Validation performed

- Live supplied portal responded over HTTPS and identified itself as Cosmos Employee Portal.
- Its public location script requests a fresh GPS reading with accuracy validation and retry.
- Exact-origin policy tested with permitted paths and rejected insecure URLs, lookalike hosts, userinfo, nonstandard ports and local/script/intent schemes.
- APK compiled, aligned and signature verified with SDK tools.

No real phone/emulator session or employee login was used here. Real GPS, successful attendance submission, file upload/download, session persistence and camera require the following phone acceptance test.

## Test on one employee Android phone

1. Install the test APK; enable installation for the application opening the APK if Android asks.
2. Launch and sign in with an authorised test employee account.
3. Submit attendance. Select **While using the app** and **Precise location** when Android asks. Compare the result against the portal's attendance record.
4. Deny location once; confirm clear failure, no attendance insertion, and recovery after enabling permission in settings.
5. Turn location off or disable internet; confirm failure/retry and no duplicate shift on retry.
6. Close/reopen, verify login behaviour and sign out; verify private views require sign-in again.
7. As an authorised admin, test the same export used on the website, save the file and open it. Test a supported upload if the portal has one.
8. Check Android back navigation, Reload and Browser actions. On small screens verify keyboard and portal navigation remain usable.
9. If the portal uses camera, test allow/deny with that actual flow. Browser remains available for features unsupported by Android WebView, including some passkey flows.

Do not distribute broadly until these checks pass. A signed test APK only proves the package builds and verifies; it does not certify the deployed backend or device GPS behaviour.
