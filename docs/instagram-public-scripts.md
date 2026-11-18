# Public Instagram TLS instrumentation references

Read-only research on2026-11-18, requested by the operator. These are third-party
findings, not live verification on our Android9/Houdini/ARMv7 IG416 environment.
No external script was installed, copied into the package, or run.

## Most directly relevant evidence

[Beeper: Reverse Engineering Instagram Video Uploads,2025-11-24](https://www.beeper.com/engineering/2025/11/24/reverse-engineering-instagram-video-uploads)
documents a certificate exception stack through
`com.facebook.mobilenetwork.internal.certificateverifier.CertificateVerifier.verify`
and `TigonMNSServiceHolder.runEVLoop`, followed by an all-overloads no-op verifier
hook. The author reports readable mitmproxy requests when combined with Eltion's
existing patches. The article explicitly warns that this disables validation and
is not suitable for an important account/public network.

This is unusually close to the operator's actual caller/rejection traces. It
supports the hook location, not a need to copy a trust-all implementation.
The old [Eltion repository](https://github.com/Eltion/Instagram-SSL-Pinning-Bypass)
currently displays GitHub's "repository disabled" page; it was not source-reviewed
or installed.

## Public JavaScript sources inspected

[KnifeLemon/Android-SSL-Pinning-Bypass](https://github.com/KnifeLemon/Android-SSL-Pinning-Bypass):
reviewed README, analysis and
[`frida/instagram_v444_bypass.js` at e423bc691eba0dfebc686930f27387b9c58fcd2a](https://github.com/KnifeLemon/Android-SSL-Pinning-Bypass/blob/e423bc691eba0dfebc686930f27387b9c58fcd2a/frida/instagram_v444_bypass.js).
The repository reports testing v442/v444/v449/v455 on Android12 x86_64. Its script
no-ops all `CertificateVerifier.verify` and `verifyWithProofOfPossession` overloads,
and adds Tigon config and Conscrypt/SSLContext trust-all hooks. It may set
`setTrustUserCertificates` and force HTTP/2. These are wider TLS/behavior changes
than the approved local trial.

Its version-based pre-v444/v444 narrative is NOT a compatibility rule: our user
already observed `verifyWithProofOfPossession` on IG416. Runtime evidence on the
actual build takes precedence. Several README/tool version claims should be
independently checked; do not copy install/upgrade instructions blindly.

[Aniketh01/Instagram-android-ssl-pinning-bypass](https://github.com/Aniketh01/Instagram-android-ssl-pinning-bypass):
reviewed README and
[`scripts/instagram-unpin.js` at4162de84022e8276e32a9e2cf912ad8d44911126](https://github.com/Aniketh01/Instagram-android-ssl-pinning-bypass/blob/4162de84022e8276e32a9e2cf912ad8d44911126/scripts/instagram-unpin.js).
README reports v433/Android15 arm64; script comments also mention422. It hooks
`TigonMNSServiceHolder.initHybrid`, modifies config before initialization, replaces
Conscrypt chain validation and injects a permissive SSLContext trust manager.
Startup timing matters; late attachment is not equivalent. README distinguishes
Frida17 REPL Java bridge from raw Python script loading.

[depreciating/Instagram-SSL-Pinning-Bypass](https://github.com/depreciating/Instagram-SSL-Pinning-Bypass):
reviewed README and
[`instagram_v435.js` at f5cf91943d90040861d8defff10cbc8ee5d7c999](https://github.com/depreciating/Instagram-SSL-Pinning-Bypass/blob/f5cf91943d90040861d8defff10cbc8ee5d7c999/instagram_v435.js).
Targets v435 and mixes verifier/PoP no-ops, Tigon configuration, trust manager,
SSLContext and obfuscated pinner hooks. Its Android9+ requirement is not proof of
IG416+Houdini compatibility. Do not apply its build-specific obfuscated class names
to our app by guesswork.

## Decision for this project

Public scripts exist and corroborate the observed verifier path. They do NOT
automatically route HTTP into a proxy or deliver parsed search data. Many disable
all validation for all hosts and are deliberately broader than our approved trial.

Keep the operator-approved local exception override with original system trust
correlation, exact build/signatures, exact three-host allowlist and30s expiry.
Only the newly approved `instagram.fcgk16-1.fna.fbcdn.net` was added, not
`*.fbcdn.net`, other regional CDNs, a Tigon startup patch, or generic trust-all.
Do not change APK/Android/Frida versions, spawn the app, change proxy settings or
adopt an external script without a separate reviewed decision.

Next acceptance is readable native HTTP hostname/status/time in the existing
remote mitmweb during the bounded trial. Search UI success/Frida override events
alone are insufficient.
