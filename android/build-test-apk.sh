#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
sdk_dir="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
if [[ -z "$sdk_dir" ]]; then echo 'Set ANDROID_SDK_ROOT to your Android SDK directory.' >&2; exit 1; fi
sdk_tools="$sdk_dir/build-tools/35.0.0"
platform="$sdk_dir/platforms/android-35/android.jar"
for tool in aapt2 d8 zipalign apksigner; do [[ -x "$sdk_tools/$tool" ]] || { echo "Missing Android build tool: $tool" >&2; exit 1; }; done
[[ -f "$platform" ]] || { echo 'Install platforms;android-35.' >&2; exit 1; }
rm -rf build
mkdir -p build/classes build/dex build/test
if command -v javac >/dev/null; then compiler=(javac); else
 [[ -n "${COSMOS_ECJ_JAR:-}" ]] || { echo "Install JDK 17 or set COSMOS_ECJ_JAR to Eclipse ecj.jar." >&2; exit 1; }
 compiler=(java -jar "$COSMOS_ECJ_JAR")
fi
"${compiler[@]}" --release 8 -d build/test app/src/main/java/in/cosmosgroups/portal/OriginPolicy.java tests/OriginPolicyTest.java
java -cp build/test in.cosmosgroups.portal.OriginPolicyTest
"$sdk_tools/aapt2" compile --dir app/src/main/res -o build/resources.zip
"$sdk_tools/aapt2" link -I "$platform" --manifest app/src/main/AndroidManifest.xml --auto-add-overlay -o build/resources.apk build/resources.zip
"${compiler[@]}" --release 8 -classpath "$platform" -d build/classes app/src/main/java/in/cosmosgroups/portal/*.java
(cd build/classes && zip -q -r ../classes.jar .)
"$sdk_tools/d8" --min-api 26 --lib "$platform" --output build/dex build/classes.jar
cp build/resources.apk build/unsigned.apk
(cd build/dex && zip -q -j ../unsigned.apk classes.dex)
"$sdk_tools/zipalign" -f -p 4 build/unsigned.apk build/aligned.apk
key_path="${COSMOS_TEST_KEYSTORE:-$PWD/test-signing.keystore}"
if [[ ! -f "$key_path" ]]; then
 keytool -genkeypair -keystore "$key_path" -storepass android -keypass android -alias androiddebugkey -dname 'CN=Cosmos Test Build,O=Cosmos,C=IN' -keyalg RSA -keysize 2048 -validity 3650 >/dev/null 2>&1
fi
"$sdk_tools/apksigner" sign --ks "$key_path" --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android --out build/Cosmos_Employee_Portal_Test.apk build/aligned.apk
"$sdk_tools/apksigner" verify --verbose build/Cosmos_Employee_Portal_Test.apk
"$sdk_tools/zipalign" -c -p 4 build/Cosmos_Employee_Portal_Test.apk
printf 'APK ready: %s\n' "$PWD/build/Cosmos_Employee_Portal_Test.apk"
