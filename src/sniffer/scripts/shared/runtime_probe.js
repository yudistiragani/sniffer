// Metadata-only: no Interceptor, Java hooks, native calls, or trust changes.
"use strict";
send({
    event: "tls.runtime_probe",
    pid: Process.id,
    arch: Process.arch,
    pointerSize: Process.pointerSize,
    modules: Process.enumerateModules()
        .filter(m => /ssl|crypto|cronet|liger|proxygen|conscrypt|houdini|ndk_translation|libart/i.test(m.name))
        .map(m => ({name: m.name, path: m.path}))
});
